import queue
import sounddevice as sd
import json
import requests
import time
import numpy as np
from openwakeword.model import Model
from vosk import Model as VoskModel, KaldiRecognizer

SAMPLE_RATE = 16000
AUDIO_BLOCKSIZE = 1280
SESSION_TIMEOUT_SECONDS = 6

oww_model = Model(
    wakeword_models=["hey_jarvis"]
)

vosk_model = VoskModel("vosk-model-small-en-us-0.15")
recognizer = KaldiRecognizer(vosk_model, SAMPLE_RATE)

audio_queue = queue.Queue()

session_active = False
last_activity_time = 0

def callback(indata, frames, time_info, status):
    if status:
        print(status)
    audio_queue.put(bytes(indata))

def jarvis_status():
    try:
        response = requests.get("http://127.0.0.1:5000/status", timeout=2)
        return response.json()
    except Exception as e:
        print("Status fetch failed:", e)
        return {"status": "Listening...", "is_busy": False}

print("Wake listener active")
print("Say: Hey Jarvis")

with sd.RawInputStream(
    samplerate=SAMPLE_RATE,
    blocksize=AUDIO_BLOCKSIZE,
    dtype="int16",
    channels=1,
    callback=callback
):
    while True:

        data = audio_queue.get()
        audio_array = np.frombuffer(data, dtype=np.int16)

        prediction = oww_model.predict(audio_array)

        # -----------------------------
        # Wake detection
        # -----------------------------
        if not session_active:

            score = prediction.get("hey_jarvis", 0)

            if score > 0.5:

                session_active = True
                recognizer.Reset()
                last_activity_time = time.time()

                print("Wake word detected: Hey Jarvis")

                try:
                    requests.get(
                        "http://127.0.0.1:5000/set_status/Listening...",
                        timeout=2
                    )
                except Exception as e:
                    print("Status update failed:", e)

                continue

        # -----------------------------
        # Active session
        # -----------------------------
        if session_active:

            status_info = jarvis_status()
            jarvis_busy = status_info.get("is_busy", False)

            # Only timeout when Jarvis is NOT speaking/thinking
            if not jarvis_busy:
                if time.time() - last_activity_time > SESSION_TIMEOUT_SECONDS:

                    session_active = False
                    recognizer.Reset()

                    try:
                        requests.get(
                            "http://127.0.0.1:5000/set_status/Listening...",
                            timeout=2
                        )
                    except Exception as e:
                        print("Timeout reset failed:", e)

                    print("Session timed out")
                    continue

            if recognizer.AcceptWaveform(data):

                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip().lower()

                if text:

                    print("Command heard:", text)

                    try:
                        url = (
                            "http://127.0.0.1:5000/simulate_heard/"
                            + text.replace(" ", "_")
                        )

                        requests.get(url, timeout=2)

                        print("Command sent")

                        # refresh session timer when user gives a command
                        last_activity_time = time.time()

                    except Exception as e:
                        print("Command send failed:", e)

                    recognizer.Reset()
