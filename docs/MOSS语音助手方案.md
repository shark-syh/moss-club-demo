# MOSS 语音助手演示方案

> 记忆文件：本项目为「社团嘉年华」展示用的 MOSS 语音助手。核心目标：按键录音 → 电脑 ASR → DeepSeek 意图解析 → 安全打开桌面文件 → TTS 语音回复，形成一个最小可演示闭环。

---

## 0. 待确认问题与默认假设

| 待确认问题 | 默认假设 |
|---|---|
| 电脑系统 | Windows 10/11 |
| ESP32-C3 具体开发板 | 常见 ESP32-C3-DevKitM-1，GPIO 可按实际板卡调整 |
| 展示现场网络 | 可连接同一 Wi-Fi；同时准备手机热点 |
| DeepSeek API Key | 已申请并可用 |
| 外壳内部空间 | 可安装一块开发板、一个小扬声器和一块电池 |
| 演示语言 | 普通话 |
| 文件操作范围 | 仅允许打开/查看桌面目录下已有文件和文件夹 |
| 演示日期 | 当前为 9 月 5 日，距离 9 月 9 日只有 4 天，因此采用「最小闭环优先」方案 |

---

## 1. 整体系统架构

### 职责划分

```text
用户说话
   │
   ▼
ESP32-C3
- I2S 麦克风采音
- 录音开始/结束
- 上传 PCM 音频
- 播放电脑返回的 WAV 音频
- LED、按钮、舵机控制
   │ Wi-Fi / USB 串口
   ▼
Windows 上位机
- ASR 语音识别
- 调用 DeepSeek
- Function Calling 意图解析
- 安全校验和打开桌面文件
- TTS 语音合成
   │
   ▼
DeepSeek API
- 普通问答
- 将「打开文件夹」等意图转成结构化工具调用
```

### 为什么 ASR 放在电脑端

1. ESP32-C3 的 RAM、算力和 Flash 有限，不适合运行高质量中文 ASR。
2. 电脑可运行 `faster-whisper`、Vosk 等本地模型，现场断网也能识别。
3. 电脑更适合处理 WAV、模型推理、缓存和异常重试。
4. ESP32 只负责实时音频采集和播放，固件复杂度低，4 天内更容易跑通。

### 通信方式

优先级建议：

1. Wi-Fi HTTP：ESP32 向电脑上传 PCM，电脑返回 JSON 和 TTS 地址。
2. USB 串口备用：传输状态、文本命令或小段音频。
3. 电脑与 ESP32 必须处于同一局域网，电脑设置固定 IP 或使用 mDNS。

推荐上位机地址：

```text
http://192.168.1.100:8765
```

---

## 2. 硬件选型清单

### 演示必需

| 部件 | 推荐型号 | 数量 | 接线要点 | 参考价 |
|---|---|---:|---|---:|
| 主控开发板 | ESP32-C3-DevKitM-1 | 1 | USB 供电和烧录 | 25~45 元 |
| I2S 麦克风 | INMP441 或 SPH0645LM4H | 1 | BCLK、LRCLK、DOUT、3.3V、GND | 10~20 元 |
| I2S 功放 | MAX98357A | 1 | DIN、BCLK、LRC、5V、GND | 10~20 元 |
| 扬声器 | 4Ω 3W 全频喇叭 | 1 | 连接 MAX98357A 输出 | 8~15 元 |
| 按钮 | 轻触按键 | 1 | GPIO 上拉，按下开始录音 | 1~3 元 |
| 状态灯 | WS2812B 单灯或普通 LED | 1 | 显示待机、录音、联网、错误状态 | 1~5 元 |
| 电源 | USB 移动电源或 5V 2A 适配器 | 1 | 最稳定，先不做锂电池管理 | 20~50 元 |
| 杜邦线、排针、洞洞板 | 常规 | 若干 | 电源线尽量独立走线 | 10~20 元 |

**必需硬件合计：约 85~175 元。**

### 可选增强

| 部件 | 推荐型号 | 用途 | 参考价 |
|---|---|---|---:|
| 舵机 | SG90 | 头部左右转动 | 8~15 元 |
| 舵机 | MG90S | 金属齿，更耐用 | 20~35 元 |
| 舵机驱动板 | PCA9685 | 多路舵机控制 | 15~25 元 |
| OLED | 0.96 英寸 SSD1306 I2C | 显示「聆听中」「思考中」等 | 10~20 元 |
| 眼睛灯 | 5mm LED 或 WS2812 灯环 | 增加 MOSS 视觉效果 | 5~20 元 |
| 锂电池模块 | 18650 + TP4056 + 升压模块 | 脱离 USB 使用 | 30~60 元 |
| 麦克风阵列 | INMP441 双麦克风 | 改善远场收音 | 20~50 元 |

### 接线建议

以 ESP32-C3 为例，预留 GPIO（实际以开发板丝印和原理图为准）：

| 信号 | GPIO 示例 |
|---|---:|
| I2S BCLK | GPIO4 |
| I2S LRCLK | GPIO5 |
| 麦克风 DOUT | GPIO6 |
| MAX98357A DIN | GPIO7 |
| 状态 LED | GPIO8 |
| 录音按钮 | GPIO9 |
| 舵机 PWM | GPIO10 |
| OLED SDA/SCL | GPIO0/GPIO1 |

注意事项：

- ESP32-C3 使用 3.3V 逻辑。
- MAX98357A 可使用 5V 供电，但数字信号仍接 ESP32 的 3.3V。
- 麦克风和功放应共地。
- 功放和舵机的电源不要直接从 ESP32 的 3.3V 引脚取电。
- 外壳前方开 1~2 mm 网孔给麦克风和扬声器，麦克风不要紧贴扬声器，避免啸叫。
- 若外壳没有安装位，先用双面胶固定，不要在演示前增加复杂机械结构。

---

## 3. ESP32-C3 固件

### 开发环境（推荐 Arduino 方案）

1. 安装 Arduino IDE 2.x。
2. 在「开发板管理器网址」中加入 ESP32 官方板卡地址。
3. 安装 `esp32 by Espressif Systems`。
4. 选择 `ESP32C3 Dev Module`。
5. 安装库：ArduinoJson；ESP32 Arduino Core 自带 WiFi、HTTPClient。
6. 选择正确 COM 口，先烧录 Blink 测试。
7. 确认电脑防火墙允许 Python 监听 8765 端口。

### 固件功能清单

- Wi-Fi 连接
- 按钮触发 4 秒录音
- I2S 麦克风采集 16 kHz PCM
- HTTP 上传到电脑
- 接收 JSON 回复
- 从电脑下载 WAV 并通过 MAX98357A 播放
- LED 状态提示

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "driver/i2s.h"

const char* WIFI_SSID = "你的WiFi名称";
const char* WIFI_PASS = "你的WiFi密码";

// 改成电脑在局域网中的固定 IP
const char* SERVER_URL = "http://192.168.1.100:8765";

#define I2S_PORT       I2S_NUM_0
#define PIN_BCLK       4
#define PIN_LRCLK      5
#define PIN_MIC_DIN    6
#define PIN_SPK_DOUT   7
#define PIN_LED        8
#define PIN_BUTTON     9

#define SAMPLE_RATE    16000
#define RECORD_SECONDS 4
#define SAMPLE_COUNT   (SAMPLE_RATE * RECORD_SECONDS)

static int16_t pcmBuffer[SAMPLE_COUNT];

void setLed(bool on) {
  digitalWrite(PIN_LED, on ? HIGH : LOW);
}

void installI2SRx() {
  i2s_driver_uninstall(I2S_PORT);

  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = SAMPLE_RATE;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
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
  pins.data_out_num = I2S_PIN_NO_CHANGE;
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

bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    setLed(!digitalRead(PIN_LED));
    delay(250);
  }

  setLed(WiFi.status() == WL_CONNECTED);
  return WiFi.status() == WL_CONNECTED;
}

void recordPcm() {
  installI2SRx();

  int32_t raw[256];
  size_t bytesRead = 0;
  int index = 0;

  while (index < SAMPLE_COUNT) {
    i2s_read(I2S_PORT, raw, sizeof(raw), &bytesRead, portMAX_DELAY);

    int count = bytesRead / sizeof(int32_t);
    for (int i = 0; i < count && index < SAMPLE_COUNT; i++) {
      // INMP441 常见输出为左对齐 24 位，右移后转为 16 位
      int32_t sample = raw[i] >> 14;
      if (sample > 32767) sample = 32767;
      if (sample < -32768) sample = -32768;
      pcmBuffer[index++] = (int16_t)sample;
    }
  }
}

void playWavFromUrl(const String& url) {
  HTTPClient http;
  if (http.begin(url) != true) return;

  int status = http.GET();
  if (status != HTTP_CODE_OK) {
    http.end();
    return;
  }

  WiFiClient* stream = http.getStreamPtr();

  // 跳过标准 PCM WAV 头；生产代码应进一步解析 fmt/data chunk
  uint8_t header[44];
  stream->readBytes(header, sizeof(header));

  installI2STx();

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
}

void sendRecording() {
  HTTPClient http;
  String endpoint = String(SERVER_URL) + "/api/command";

  if (!http.begin(endpoint)) return;
  http.addHeader("Content-Type", "audio/pcm; rate=16000; channels=1");

  int bytes = http.POST((uint8_t*)pcmBuffer, SAMPLE_COUNT * sizeof(int16_t));

  if (bytes == HTTP_CODE_OK) {
    String response = http.getString();

    DynamicJsonDocument doc(2048);
    if (deserializeJson(doc, response) == DeserializationError::Ok) {
      String reply = doc["reply"] | "没有收到回复";
      String ttsUrl = doc["tts_url"] | "";

      Serial.println(reply);

      if (ttsUrl.length() > 0) {
        playWavFromUrl(ttsUrl);
      }
    }
  }

  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);

  setLed(false);
  connectWiFi();

  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  if (digitalRead(PIN_BUTTON) == LOW) {
    delay(30);

    if (digitalRead(PIN_BUTTON) == LOW) {
      setLed(true);             // 录音状态
      recordPcm();
      setLed(false);

      if (WiFi.status() == WL_CONNECTED) {
        sendRecording();
      } else {
        Serial.println("Wi-Fi unavailable");
      }

      while (digitalRead(PIN_BUTTON) == LOW) {
        delay(10);
      }
    }
  }
}
```

固件说明：

- GPIO 只是示例，必须根据实际开发板修改。
- 如果 I2S 驱动卸载后重装不稳定，可改成两个 I2S 控制器，或让电脑播放 TTS。
- 现场首先保证「按键录音、电脑识别、电脑回答、扬声器播放」闭环，不要先做唤醒词和复杂舵机动作。

---

## 4. 电脑端软件

### ASR 选型

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| `faster-whisper base/small` 本地 | 无单次费用，断网可用，中文效果好 | 首次下载模型，CPU 有延迟 | 首选 |
| Vosk 中文模型 | 轻量、启动快、离线 | 中文连续语音准确率一般 | 备用 |
| 云端讯飞/阿里/腾讯 ASR | 中文识别成熟 | 依赖网络和账号 | 现场网络稳定时备用 |
| Windows SAPI | 无需额外服务 | 中文语音包不一定安装 | 仅作应急 |

建议：

- 电脑预先下载 `faster-whisper base` 模型。
- 录音固定为 16 kHz、单声道、16-bit PCM。
- 演示环境使用 USB 麦克风或 ESP32 麦克风二选一，避免双重回声。

### TTS 选型

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| Windows SAPI + pyttsx3 | 本地、免费、稳定 | 音色普通 | 首选 |
| Edge TTS | 中文音色自然 | 依赖网络 | 网络正常时可选 |
| 云端 TTS | 音质最好 | 网络和 API 费用 | 不作为唯一方案 |

### Python 上位机依赖

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install fastapi uvicorn python-multipart openai faster-whisper pyttsx3
```

设置 DeepSeek Key：

```powershell
$env:DEEPSEEK_API_KEY = "你的 API Key"
```

### Function Calling 与安全执行模板

```python
# server.py
import io
import json
import os
import tempfile
import wave
from pathlib import Path
from urllib.parse import quote

import pyttsx3
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from faster_whisper import WhisperModel
from openai import OpenAI

app = FastAPI()

HOST = "0.0.0.0"
PORT = 8765
DESKTOP = Path.home() / "Desktop"

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com"
)

# 预先加载模型，避免每次请求重复加载
asr_model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_desktop_item",
            "description": "仅打开或查看桌面目录下已有文件或文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "相对于桌面目录的路径，例如 社团嘉年华 或 社团嘉年华\\说明.pdf"
                    }
                },
                "required": ["relative_path"],
                "additionalProperties": False
            }
        }
    }
]

SYSTEM_PROMPT = """
你是学校展示用的 MOSS 机器人。
你只能做两类事情：
1. 回答普通问题；
2. 当用户明确要求打开或查看桌面文件、文件夹时调用 open_desktop_item。

绝对禁止执行删除、修改、移动、复制、重命名、写入、安装、
运行程序、执行命令、关机、联网扫描等操作。
路径必须是相对于 Windows 桌面的相对路径。
如果用户要求超出范围，直接说明只能打开或查看桌面项目。
"""

def pcm_to_wav(pcm: bytes) -> str:
    file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    file.close()

    with wave.open(file.name, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)

    return file.name

def transcribe(pcm: bytes) -> str:
    wav_path = pcm_to_wav(pcm)
    try:
        segments, _ = asr_model.transcribe(
            wav_path,
            language="zh",
            beam_size=1,
            vad_filter=True
        )
        return "".join(segment.text for segment in segments).strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)

def safe_open_desktop_item(relative_path: str) -> tuple[bool, str]:
    """
    最终安全边界：
    - 只接受相对路径
    - 只允许 Desktop 下的已有文件/文件夹
    - 不调用 shell、PowerShell 或 subprocess
    """
    if not relative_path:
        return False, "路径为空"

    candidate_text = relative_path.replace("/", "\\").strip()

    # 拒绝绝对路径、UNC 路径、命令字符和路径穿越
    forbidden = [":", "\x00", "*", "?", "|", ">", "<", '"']
    if candidate_text.startswith("\\"):
        return False, "不允许绝对路径"
    if any(ch in candidate_text for ch in forbidden):
        return False, "路径包含非法字符"

    relative = Path(candidate_text)
    if ".." in relative.parts:
        return False, "不允许访问桌面以外的目录"

    desktop = DESKTOP.resolve()
    target = (desktop / relative).resolve()

    try:
        target.relative_to(desktop)
    except ValueError:
        return False, "目标不在桌面目录内"

    if not target.exists():
        return False, "桌面上不存在该项目"

    # Windows 原生打开动作，不经过命令解释器
    os.startfile(str(target))
    return True, f"已打开 {target.name}"

def decide(user_text: str) -> str:
    response = client.chat.completions.create(
        model="deepseek-chat",
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ],
        tools=TOOLS,
        tool_choice="auto",
        timeout=12
    )

    message = response.choices[0].message

    if message.tool_calls:
        for call in message.tool_calls:
            if call.function.name != "open_desktop_item":
                return "这个操作不在允许范围内。"

            args = json.loads(call.function.arguments)
            ok, result = safe_open_desktop_item(
                args.get("relative_path", "")
            )
            return result

    return message.content or "我暂时没有理解你的问题。"

@app.post("/api/command")
async def command(request: Request):
    pcm = await request.body()

    if len(pcm) < 1000:
        return JSONResponse(
            {"reply": "录音太短，请再说一次", "tts_url": ""},
            status_code=400
        )

    try:
        text = transcribe(pcm)

        if not text:
            reply = "我没有听清，请再说一次。"
        else:
            reply = decide(text)

        tts_url = f"http://{request.url.hostname}:{PORT}/tts?text={quote(reply)}"

        return {
            "recognized_text": text,
            "reply": reply,
            "tts_url": tts_url
        }

    except Exception:
        # 不把 API Key、路径或堆栈信息暴露给机器人
        return JSONResponse(
            {"reply": "服务暂时不可用，请使用备用演示模式。", "tts_url": ""},
            status_code=500
        )

@app.get("/tts")
def tts(text: str):
    output = Path(tempfile.mktemp(suffix=".wav"))

    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.save_to_file(text, str(output))
    engine.runAndWait()
    engine.stop()

    return FileResponse(
        output,
        media_type="audio/wav",
        filename="moss_reply.wav"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
```

启动：

```powershell
.venv\Scripts\activate
python server.py
```

### 安全机制（三层必须同时存在）

1. **模型层限制**：系统提示词和 Function Calling 只暴露 `open_desktop_item`。
2. **参数层限制**：拒绝绝对路径、`..`、UNC 路径、命令字符和桌面外路径。
3. **执行层限制**：只调用 `os.startfile()`，禁止 `subprocess`、`os.system`、PowerShell、cmd。

禁止实现以下功能：

```text
删除、写入、修改、移动、复制、重命名、下载、安装、运行任意程序、
执行系统命令、关机、格式化、注册表修改、打开桌面以外路径。
```

---

## 5. 端到端时序

```text
1. 用户按下录音按钮
2. ESP32 录制 4 秒 PCM
3. ESP32 POST /api/command
4. 电脑将 PCM 包装成 WAV
5. faster-whisper 转成中文文本
6. 文本发送给 DeepSeek
7. DeepSeek 返回普通文本或 open_desktop_item 工具调用
8. 上位机校验路径是否位于 Desktop 下
9. 合法时调用 os.startfile()
10. 上位机生成 TTS WAV
11. 返回 reply 和 tts_url
12. ESP32 下载 WAV
13. MAX98357A 播放语音
14. LED 恢复待机状态
```

### 异常处理

| 异常 | 处理方式 |
|---|---|
| Wi-Fi 连接失败 | LED 快闪；切换手机热点；电脑端提供键盘输入备用 |
| DeepSeek 超时 | 重试一次；仍失败则返回固定话术 |
| ASR 识别为空 | 回复「我没有听清，请再说一次」 |
| 文件不存在 | 回复「桌面上不存在该项目」 |
| 路径穿越或危险请求 | 拒绝执行并说明仅支持打开/查看 |
| TTS 失败 | 电脑扬声器直接播放，ESP32 只显示文字 |
| ESP32 断线 | 使用电脑端网页或键盘模拟演示 |
| 现场断网 | 使用本地 ASR、本地 TTS；DeepSeek 准备固定问答和固定文件指令 |
| 断电 | USB 移动电源、备用 USB 线、已烧录备用 ESP32 |

---

## 6. 演示功能与里程碑

### 最终演示功能

| 优先级 | 功能 | 验收标准 |
|---|---|---|
| P0 | 按键录音 | 按下按钮后录音 4 秒 |
| P0 | 中文 ASR | 能识别「打开桌面的社团嘉年华文件夹」 |
| P0 | DeepSeek 普通问答 | 能回答 3~5 个预设问题 |
| P0 | 打开桌面文件夹 | 只打开白名单内目录 |
| P0 | 语音回复 | ESP32 扬声器播报结果 |
| P1 | LED 状态 | 待机、录音、思考、错误四种状态 |
| P1 | 头部舵机 | 回答时左右转动 |
| P2 | OLED 屏幕 | 显示识别文本和状态 |
| P2 | 唤醒词 | 「你好 MOSS」后开始录音 |

### 9 月 5 日至 9 月 9 日冲刺计划

| 日期 | 任务 | 交付物 |
|---|---|---|
| 9 月 5 日 | 采购/确认麦克风、功放、扬声器；Arduino 烧录 Blink；电脑安装 Python 环境 | 硬件通电，ESP32 能联网 |
| 9 月 6 日 | 完成 ESP32 录音上传；完成电脑 ASR；准备桌面演示文件夹 | 能看到识别文本 |
| 9 月 7 日 | 接入 DeepSeek Function Calling；完成路径白名单和 `os.startfile` | 语音打开指定桌面文件夹 |
| 9 月 8 日 | 接入 TTS；连续测试 30 次；准备离线固定话术和备用电脑操作 | 端到端闭环稳定 |
| 9 月 9 日 | 现场部署、线路固定、准备备用电源和备用 ESP32 | 可连续演示 2 小时 |

不建议在 9 月 8 日之后新增屏幕、唤醒词或复杂机械结构。

---

## 7. 风险与备用方案

### API 延迟

- DeepSeek 请求超时设置为 12 秒。
- 温度设置为 0.1，减少工具调用漂移。
- 对常见演示问题做本地缓存。
- 现场准备固定问答模式：

```text
「你好」 -> 「你好，我是 MOSS。」
「你是谁」 -> 「我是社团嘉年华展示机器人。」
「打开社团嘉年华」 -> 直接打开固定白名单路径。
```

### 网络中断

- ASR 使用本地 `faster-whisper`。
- TTS 使用 Windows SAPI。
- DeepSeek 不可用时，进入本地关键词模式：
  - 包含「打开」+「社团嘉年华」时打开固定目录。
  - 其他问题返回固定话术。
- 准备手机热点和网线。

### 识别不准确

- 按键录音比持续监听更可靠。
- 录音前 LED 亮起，提示用户开始说话。
- 统一用户说法，例如只演示：
  - 「打开桌面的社团嘉年华文件夹」
  - 「打开桌面的活动说明文件」
- 使用外接 USB 麦克风作为电脑端备用输入。

### 电源和机械风险

- 首次演示使用 USB 移动电源，不使用临时锂电池方案。
- 舵机单独供电并共地。
- 所有线缆用热熔胶或扎带固定。
- 准备备用 USB 线、开发板、喇叭和按键。

---

## 8. 第一步行动清单

### 今天

1. 确认 ESP32-C3 开发板型号和 GPIO。
2. 购买或找齐 INMP441、MAX98357A、4Ω 喇叭、按钮和 USB 电源。
3. 在电脑安装 Arduino IDE、Python 3.11 和 `faster-whisper`。
4. 创建桌面目录：`社团嘉年华`，放入 2~3 个只读演示文件。

### 明天

1. 烧录 ESP32 Wi-Fi 和 I2S 采音代码。
2. 跑通电脑端 `/api/command`，确认能打印识别文本。
3. 接入 DeepSeek，测试普通问答和非法指令拒绝。
4. 测试合法路径打开和 `..`、绝对路径、删除请求拦截。

### 后天

1. 接通 MAX98357A，完成 TTS 播放。
2. 连续跑 30 次完整流程，记录失败原因。
3. 固化线缆和外壳安装位置。
4. 准备离线固定话术、手机热点、备用电源和备用 ESP32。
