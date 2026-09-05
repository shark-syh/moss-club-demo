/*
 * MOSS 语音助手 —— ESP32-C3 固件
 *
 * 功能：
 *   - Wi-Fi 连接
 *   - 轻触开关（GPIO1）触发 4 秒录音
 *   - I2S 麦克风 INMP441 采集 16kHz 单声道 PCM
 *   - HTTP POST 上传到上位机 /api/command
 *   - 接收 JSON（reply + tts_url）
 *   - 从 tts_url 下载 WAV 并通过 MAX98357A 播放
 *   - WS2812 灯环（GPIO10）显示状态
 *
 * 依赖库（Arduino IDE 库管理器安装）：
 *   - ArduinoJson
 *   - Adafruit NeoPixel
 *
 * 接线与 GPIO 映射（详见 docs/接线方案与端口定义.md）：
 *   I2S BCLK   -> GPIO4   （麦克风 SCK 与功放 BCLK 共用）
 *   I2S LRCLK  -> GPIO5   （麦克风 WS  与功放 LRC  共用）
 *   麦克风数据  -> GPIO6   （INMP441 SD   → ESP32，输入）
 *   功放数据   -> GPIO7   （ESP32 → MAX98357A DIN，输出）
 *   录音按钮   -> GPIO1   （内部上拉，按下为 LOW）
 *   WS2812 DIN -> GPIO10  （灯环数据）
 *
 * 注意：ESP32-C3 只有一个 I2S0，因此录音(RX)与播放(TX)复用同一端口，
 *       在 installI2SRx() / installI2STx() 之间切换模式。
 *       所有 GPIO 请以实际开发板丝印为准修改。
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "driver/i2s.h"

// ---------------- 用户配置 ----------------
const char* WIFI_SSID = "你的WiFi名称";
const char* WIFI_PASS = "你的WiFi密码";

// 改成电脑在局域网中的固定 IP
const char* SERVER_URL = "http://192.168.1.100:8765";

// ---------------- GPIO 定义 ----------------
#define PIN_BCLK       4
#define PIN_LRCLK      5
#define PIN_MIC_DIN    6   // INMP441 SD -> ESP32
#define PIN_SPK_DOUT   7   // ESP32 -> MAX98357A DIN
#define PIN_BUTTON     1   // 轻触开关，内部上拉
#define PIN_LED_RING   10  // WS2812 DIN

// ---------------- I2S / 采样参数 ----------------
#define I2S_PORT         I2S_NUM_0
#define SAMPLE_RATE      16000
#define RECORD_SECONDS   4
#define SAMPLE_COUNT     (SAMPLE_RATE * RECORD_SECONDS)

// ---------------- WS2812 灯环 ----------------
#define LED_COUNT        16
Adafruit_NeoPixel ring(LED_COUNT, PIN_LED_RING, NEO_GRB + NEO_KHZ800);

// 状态颜色（R,G,B）
const uint32_t COLOR_IDLE      = ring.Color(0, 0, 80);    // 蓝：待机
const uint32_t COLOR_RECORDING = ring.Color(120, 0, 0);   // 红：录音中
const uint32_t COLOR_THINKING  = ring.Color(0, 120, 0);   // 绿：处理/联网中
const uint32_t COLOR_PLAYING  = ring.Color(80, 0, 120);   // 紫：播放中
const uint32_t COLOR_ERROR    = ring.Color(120, 60, 0);   // 橙：错误

static int16_t pcmBuffer[SAMPLE_COUNT];

// ---------------- 灯环状态显示 ----------------
void setRingColor(uint32_t color) {
  ring.fill(color, 0, LED_COUNT);
  ring.show();
}

void ringBlink(uint32_t color, int times, int delayMs = 150) {
  for (int i = 0; i < times; i++) {
    setRingColor(color);
    delay(delayMs);
    setRingColor(ring.Color(0, 0, 0));
    delay(delayMs);
  }
}

// ---------------- I2S 配置（公用参数） ----------------
void installI2SRx() {
  i2s_driver_uninstall(I2S_PORT);

  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = SAMPLE_RATE;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;   // INMP441 L/R 接地 = 左声道
  config.communication_format = I2S_COMM_FORMAT_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = 8;
  config.dma_buf_len = 256;
  config.use_apll = false;
  config.tx_desc_auto_clear = false;
  config.fixed_mclk = 0;

  i2s_pin_config_t pins = {};
  pins.bck_io_num = PIN_BCLK;
  pins.ws_io_num = PIN_LRCLK;
  pins.data_out_num = I2S_PIN_NO_CHANGE;   // 录音模式不用输出
  pins.data_in_num = PIN_MIC_DIN;

  i2s_driver_install(I2S_PORT, &config, 0, nullptr);
  i2s_set_pin(I2S_PORT, &pins);
  i2s_zero_dma_buffer(I2S_PORT);
}

void installI2STx() {
  i2s_driver_uninstall(I2S_PORT);

  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  config.sample_rate = SAMPLE_RATE;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  config.communication_format = I2S_COMM_FORMAT_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = 8;
  config.dma_buf_len = 256;
  config.use_apll = false;
  config.tx_desc_auto_clear = true;
  config.fixed_mclk = 0;

  i2s_pin_config_t pins = {};
  pins.bck_io_num = PIN_BCLK;
  pins.ws_io_num = PIN_LRCLK;
  pins.data_out_num = PIN_SPK_DOUT;
  pins.data_in_num = I2S_PIN_NO_CHANGE;

  i2s_driver_install(I2S_PORT, &config, 0, nullptr);
  i2s_set_pin(I2S_PORT, &pins);
  i2s_zero_dma_buffer(I2S_PORT);
}

// ---------------- Wi-Fi ----------------
bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    ringBlink(COLOR_THINKING, 1, 250);
    delay(250);
  }

  if (WiFi.status() == WL_CONNECTED) {
    setRingColor(COLOR_IDLE);
  } else {
    ringBlink(COLOR_ERROR, 5, 200);
  }
  return WiFi.status() == WL_CONNECTED;
}

// ---------------- 录音 ----------------
void recordPcm() {
  installI2SRx();
  setRingColor(COLOR_RECORDING);

  int32_t raw[256];
  size_t bytesRead = 0;
  int index = 0;

  while (index < SAMPLE_COUNT) {
    i2s_read(I2S_PORT, raw, sizeof(raw), &bytesRead, portMAX_DELAY);

    int count = bytesRead / sizeof(int32_t);
    for (int i = 0; i < count && index < SAMPLE_COUNT; i++) {
      // INMP441 常见输出为左对齐 24 位，右移后转 16 位
      int32_t sample = raw[i] >> 14;
      if (sample > 32767) sample = 32767;
      if (sample < -32768) sample = -32768;
      pcmBuffer[index++] = (int16_t)sample;
    }
  }
  installI2STx(); // 释放 RX，切回可用状态
}

// ---------------- 播放 WAV ----------------
void playWavFromUrl(const String& url) {
  HTTPClient http;
  if (!http.begin(url)) return;

  int status = http.GET();
  if (status != HTTP_CODE_OK) {
    http.end();
    return;
  }

  WiFiClient* stream = http.getStreamPtr();

  // 跳过标准 44 字节 PCM WAV 头；生产代码应进一步解析 fmt/data chunk
  uint8_t header[44];
  stream->readBytes(header, sizeof(header));

  installI2STx();
  setRingColor(COLOR_PLAYING);

  uint8_t buffer[1024];
  while (http.connected()) {
    int available = stream->available();
    if (available <= 0) {
      delay(5);
      continue;
    }
    int length = stream->readBytes(buffer, min(available, (int)sizeof(buffer)));
    if (length <= 0) break;

    size_t written = 0;
    i2s_write(I2S_PORT, buffer, length, &written, portMAX_DELAY);
  }

  http.end();
  setRingColor(COLOR_IDLE);
}

// ---------------- 上传录音并处理 ----------------
void sendRecording() {
  HTTPClient http;
  String endpoint = String(SERVER_URL) + "/api/command";

  if (!http.begin(endpoint)) return;
  http.addHeader("Content-Type", "audio/pcm; rate=16000; channels=1");

  setRingColor(COLOR_THINKING);

  int bytes = http.POST((uint8_t*)pcmBuffer, SAMPLE_COUNT * sizeof(int16_t));

  if (bytes == HTTP_CODE_OK) {
    String response = http.getString();

    DynamicJsonDocument doc(2048);
    if (deserializeJson(doc, response) == DeserializationError::Ok) {
      String reply = doc["reply"] | "没有收到回复";
      String ttsUrl = doc["tts_url"] | "";

      Serial.println("识别: " + String(doc["recognized_text"] | ""));
      Serial.println("回复: " + reply);

      if (ttsUrl.length() > 0) {
        playWavFromUrl(ttsUrl);
      }
    }
  } else {
    ringBlink(COLOR_ERROR, 4, 150);
  }

  http.end();
  setRingColor(COLOR_IDLE);
}

// ---------------- 初始化 ----------------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);

  ring.begin();
  ring.setBrightness(80);
  ring.show();

  setRingColor(COLOR_THINKING); // 开机联网中
  connectWiFi();

  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

// ---------------- 主循环 ----------------
void loop() {
  // 按下按钮开始一次录音-上传-播放流程
  if (digitalRead(PIN_BUTTON) == LOW) {
    delay(30);
    if (digitalRead(PIN_BUTTON) == LOW) {
      recordPcm();

      if (WiFi.status() == WL_CONNECTED) {
        sendRecording();
      } else {
        Serial.println("Wi-Fi unavailable");
        ringBlink(COLOR_ERROR, 5, 200);
      }

      // 等待按钮松开
      while (digitalRead(PIN_BUTTON) == LOW) {
        delay(10);
      }
    }
  }

  // 慢速呼吸提示待机（可选，占 CPU 很低）
  delay(5);
}
