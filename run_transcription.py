import pyaudio
import wave
import base64
import json
from io import BytesIO
import websockets
import ssl
import asyncio
import time
import argparse

# Set the parameters for the recording
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 16000
END_OF_RECEIVE_TIMEOUT = 20


audio = pyaudio.PyAudio()


def record_audio_thread(end_of_send_event, websocket, loop):
    # Open the stream for recording
    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

    print("Recording...")

    # Record the audio in chunks and put in the queue
    while not end_of_send_event.is_set():
        data = stream.read(CHUNK)
        # Use BytesIO to create an in-memory WAV file
        with BytesIO() as wav_file:
            with wave.open(wav_file, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(audio.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join([data]))

            # Move the pointer to the beginning of the BytesIO object
            wav_file.seek(0)

            # Read the in-memory WAV file and encode it to Base64
            base64_encoded_data = base64.b64encode(wav_file.read())

        # Convert to string for JSON
        base64_string = base64_encoded_data.decode("utf-8")

        # Create JSON object
        json_object = json.dumps({"audio": base64_string, "uid": "1234567890"})
        # Send the audio message
        asyncio.run_coroutine_threadsafe(websocket.send(json_object), loop)

    print("Finished recording.")

    # Stop and close the stream
    stream.stop_stream()
    stream.close()
    audio.terminate()


async def record_audio(end_of_send_event, websocket, loop):
    await asyncio.to_thread(record_audio_thread, end_of_send_event, websocket, loop)


async def receive_messages(end_of_send_event, websocket):
    received_stop_message = False
    last_transcript = None
    all_transcripts = []
    end_of_send_time = None
    while not received_stop_message:
        # Check if event is set
        if end_of_send_event.is_set():
            end_of_send_time = time.time()

        # Check if timeout
        if end_of_send_time is not None and time.time() - end_of_send_time > END_OF_RECEIVE_TIMEOUT:
            break
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        # Parse message
        message = json.loads(message)
        if "transcript" in message:
            last_transcript = message["transcript"]
            all_transcripts.append(last_transcript)
        # Check if finished is in message dict
        if "finished" in message:
            received_stop_message = True
        print(message)


async def wait_for_user_input(end_of_send_event, websocket):
    # Use asyncio.to_thread to run the blocking input() in a separate thread
    await asyncio.to_thread(input, "Press Enter to stop...")
    end_of_send_event.set()
    await websocket.send(json.dumps({"stoppedRecording": True}))


async def connect_websocket():
    args = parse_arguments()

    # Create a context to disable SSL certificate verification
    ssl_context = None
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # End event to coordinate the end of recording, sending and receiving
    end_of_send_event = asyncio.Event()

    # Create headers
    authorization_header = "Bearer " + args.key
    user_id_header = "1234567890"

    async with websockets.connect(
        args.url,
        ssl=ssl_context,
        ping_timeout=None,
        extra_headers=[("Authorization", authorization_header), ("X-End-UserID", user_id_header)],
    ) as websocket:
        # Send the first message
        initial_message = json.dumps(
            {"language": args.language, "hotwords": args.hotwords, "manual_punctuation": args.manual_punctuation}
        )
        await websocket.send(initial_message)

        loop = asyncio.get_running_loop()

        receive_task = asyncio.create_task(receive_messages(end_of_send_event, websocket))

        recording_task = asyncio.create_task(record_audio(end_of_send_event, websocket, loop))

        user_input_task = asyncio.create_task(wait_for_user_input(end_of_send_event, websocket))
        await asyncio.gather(receive_task, user_input_task, recording_task)

    print("Over and out.")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Process command line arguments.")
    parser.add_argument("--url", type=str, required=True, help="Websocket URL")
    parser.add_argument("--language", type=str, required=True, help='Language ("fr" or "en" or "it")')
    parser.add_argument("--manual_punctuation", type=bool, required=True, help="Manual punctuation flag")
    parser.add_argument("--hotwords", type=str, required=True, help="Hotwords string (comma separated))")
    parser.add_argument("--key", type=str, required=True, help="API key")
    return parser.parse_args()


def main():
    asyncio.run(connect_websocket())


if __name__ == "__main__":
    main()
