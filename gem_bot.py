import google.generativeai as genai
import json
import speech_recognition as sr
import asyncio
import websockets
import os
from dotenv import load_dotenv
import threading
import time

# Load environment variables
load_dotenv()
GEMINI_API_KEY = "AIzaSyAFMrciJiaw3rlImT3mRz-0A3fKjs5aO7c" # api key

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY in environment variables")

# Configure API
genai.configure(api_key=GEMINI_API_KEY)

# Set up the model
generation_config = {
    "temperature": 0.1,
    "top_p": 0.95,
    "top_k": 0,
    "max_output_tokens": 1024,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
    safety_settings=safety_settings
)

# System prompt template
SYSTEM_PROMPT = """
You are a robot command parser. Convert voice commands into JSON format with exactly 4 elements: 
["intent", "direction", "value", "unit"]

Possible values:
- intent: "move", "turn", "stop", or "scan" 
- direction: "forward", "backward", "left", "right", or null
- value: number as string or null
- unit: "cm", "degree", or null

Rules:
1. Normalize synonyms:
   - "go", "advance" → "move" with "forward"
   - "back", "retreat" → "move" with "backward"
   - "rotate" → "turn"
   - "ahead" → "forward"

2. Extract numerical values

3. Handle compound commands by returning a list of lists

4. For incomplete commands:
   - "move forward" → ["move", "forward", null, null]
   - "turn left" → ["turn", "left", null, null]
   - "stop" → ["stop", null, null, null]

5. If the intent is "stop", the robot must stop immediately

6. For scan commands:
   - "scan", "scan area", "perform scan" → ["scan", null, null, null]
   - Scan always means a 360° turn to the right

7. Return only JSON, no additional text

Example outputs:
- "move forward 50 cm" → ["move", "forward", "50", "cm"]
- "rotate to the right 45" → ["turn", "right", "45", null]
- "go ahead 30 cm then turn left 90 degrees" → [["move", "forward", "30", "cm"], ["turn", "left", "90", "degree"]]
- "scan the area" → ["scan", null, null, null]
- "perform full scan" → ["scan", null, null, null]
- "stop now" → ["stop", null, null, null]
"""

def parse_command(command_text):
    """Convert voice command to structured JSON"""
    try:
        # Format the prompt
        full_prompt = f"{SYSTEM_PROMPT}\n\nCommand: {command_text}\nOutput:"
        
        # Generate response
        response = model.generate_content(full_prompt)
        
        # Extract JSON from response
        json_str = response.text.strip()
        
        # Handle Gemini's markdown formatting
        if json_str.startswith("```json"):
            json_str = json_str[7:-3].strip()
        elif json_str.startswith("```"):
            json_str = json_str[3:-3].strip()
        
        # Handle array output directly
        if json_str.startswith("[") and json_str.endswith("]"):
            return json.loads(json_str)
        
        # Handle Gemini sometimes returning just the array without quotes
        if "[" in json_str and "]" in json_str:
            start = json_str.index("[")
            end = json_str.index("]") + 1
            json_str = json_str[start:end]
            return json.loads(json_str)
        # Add unit normalization in the parser
        if unit == "centimeters" or unit == "cms":
            unit = "cm"
        
        # Fallback to error if format not recognized
        return ["error", None, None, None]
    
    except Exception as e:
        print(f"Error parsing command: {e}")
        return ["error", None, None, None]

def voice_to_command():
    """Capture voice and convert to JSON command"""
    recognizer = sr.Recognizer()
    with sr.Microphone() as mic:
        print("\nListening... (speak now)")
        recognizer.adjust_for_ambient_noise(mic, duration=1)
        try:
            audio = recognizer.listen(mic, timeout=5, phrase_time_limit=7)
        except sr.WaitTimeoutError:
            print("No speech detected within timeout period")
            return None
    
    try:
        # Convert speech to text
        text = recognizer.recognize_google(audio).lower()
        print(f"Recognized: {text}")
        
        # Parse to JSON command
        return parse_command(text)
    except sr.UnknownValueError:
        print("Google Speech Recognition could not understand audio")
    except sr.RequestError as e:
        print(f"Could not request results from Google Speech Recognition service; {e}")
    except Exception as e:
        print(f"Voice recognition error: {e}")
    
    return None

async def send_to_esp32(command):
    """Send JSON command to ESP32"""
    # Replace with your ESP32's actual IP address
    ESP32_IP = "192.168.164.20"  # CHANGE THIS TO YOUR ESP32'S IP
    #PORT = 8080 #
    uri = f"ws://{ESP32_IP}:80"
    print(f"Attempting to connect to {uri}") #
    
    try:
        async with websockets.connect(uri, ping_timeout=5) as websocket:
            # Convert command to string
            command_str = json.dumps(command)
            await websocket.send(command_str)
            print(f"Sent to ESP32: {command_str}")
            
            # Wait for acknowledgment (optional)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                print(f"ESP32 response: {response}")
            except asyncio.TimeoutError:
                print("No response from ESP32 (acknowledgment timeout)")
                return False #
                
    except websockets.exceptions.ConnectionClosedError:
        print("Connection closed unexpectedly by ESP32")
    except asyncio.TimeoutError:
        print("Connection to ESP32 timed out")
        print("Connection timed out after 5 seconds. Possible causes:")
        print("- ESP32 not powered on")
        print("- Incorrect IP address")
        print("- Different network segments")
        print("- Firewall blocking port 8080")
    except ConnectionRefusedError:
        print("Connection refused. Is WebSocket server running on ESP32?")
    except OSError as e:
        if "WinError 10061" in str(e):
            print("ESP32 actively refused connection. Check port number.")
        else:
            print(f"Network error: {e}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
    
    return False

def process_command():
    """Main function to handle voice command processing"""
    command = voice_to_command()
    if command:
        print(f"Command parsed: {command}")
        asyncio.run(send_to_esp32(command))
    else:
        print("No valid command to send")

def continuous_listener():
    """Run in a loop to continuously listen for commands"""
    print("Voice Command Robot Controller")
    print("==============================")
    print("Press Ctrl+C to exit")
    
    while True:
        process_command()
        time.sleep(1)  # Brief pause between commands

if __name__ == "__main__":
    # Test with sample commands if needed
    # test_commands = [
    #     "rotate to the right 45",
    #     "move forward 90 cm",
    #     "go ahead 50 centimeters",
    #     "turn left 30 degrees",
    #     "stop now",
    #     "advance 40 and rotate right 30 degrees",
    #     "backward 100 cm"
    # ]
    # 
    # for command in test_commands:
    #     result = parse_command(command)
    #     print(f"Command: '{command}'")
    #     print(f"JSON Output: {json.dumps(result, indent=2)}")
    #     print("-" * 60)
    
    # Start continuous listening
    try:
        continuous_listener()
    except KeyboardInterrupt:
        print("\nProgram terminated by user")