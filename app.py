import os
import re
import time
import threading
import requests

from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

from google import genai
from google.genai import errors


# =========================================================
# LOAD ENVIRONMENT
# =========================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)

if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY is missing in .env file"
    )


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)


# =========================================================
# GEMINI CLIENT
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# TOOL HISTORY
# =========================================================

tool_history = []
history_lock = threading.Lock()


def log_tool(tool_name, details):

    with history_lock:

        tool_history.insert(
            0,
            {
                "tool": tool_name,
                "details": details,
                "time": datetime.now().strftime(
                    "%H:%M:%S"
                )
            }
        )

        if len(tool_history) > 50:
            tool_history.pop()


# =========================================================
# 1. CALCULATOR
# =========================================================

def calculator(
    a: float,
    b: float,
    operation: str
) -> float:

    if operation == "add":
        return a + b

    elif operation == "subtract":
        return a - b

    elif operation == "multiply":
        return a * b

    elif operation == "divide":

        if b == 0:
            return 0

        return a / b

    return 0


# =========================================================
# 2. WEATHER
# =========================================================

def weather_tool(city: str) -> dict:

    try:

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
        )

        geo_response = requests.get(
            geo_url,
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json"
            },
            timeout=10
        )

        geo_response.raise_for_status()

        geo_data = geo_response.json()

        if (
            "results" not in geo_data
            or not geo_data["results"]
        ):

            return {
                "error": f"Could not find city: {city}"
            }

        location = geo_data["results"][0]

        latitude = location["latitude"]
        longitude = location["longitude"]

        city_name = location["name"]
        country = location.get("country", "")

        weather_url = (
            "https://api.open-meteo.com/v1/forecast"
        )

        weather_response = requests.get(
            weather_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "wind_speed_10m"
                ),
                "timezone": "auto"
            },
            timeout=10
        )

        weather_response.raise_for_status()

        weather_data = weather_response.json()

        current = weather_data["current"]

        return {
            "city": city_name,
            "country": country,
            "temperature": current["temperature_2m"],
            "humidity": current["relative_humidity_2m"],
            "wind_speed": current["wind_speed_10m"]
        }

    except Exception as e:

        return {
            "error": str(e)
        }


# =========================================================
# 3. DATE & TIME
# =========================================================

def datetime_tool() -> dict:

    now = datetime.now()

    return {
        "date": now.strftime("%d-%m-%Y"),
        "time": now.strftime("%I:%M:%S %p"),
        "day": now.strftime("%A")
    }


# =========================================================
# 4. UNIT CONVERTER
# =========================================================

def unit_converter(
    value: float,
    from_unit: str,
    to_unit: str
) -> dict:

    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    # LENGTH

    length_units = {
        "meter": 1,
        "meters": 1,
        "m": 1,

        "kilometer": 1000,
        "kilometers": 1000,
        "km": 1000,

        "centimeter": 0.01,
        "centimeters": 0.01,
        "cm": 0.01,

        "mile": 1609.344,
        "miles": 1609.344,
        "mi": 1609.344,

        "foot": 0.3048,
        "feet": 0.3048,
        "ft": 0.3048
    }

    if (
        from_unit in length_units
        and to_unit in length_units
    ):

        meters = (
            value * length_units[from_unit]
        )

        result = (
            meters / length_units[to_unit]
        )

        return {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": result
        }

    # WEIGHT

    weight_units = {
        "gram": 1,
        "grams": 1,
        "g": 1,

        "kilogram": 1000,
        "kilograms": 1000,
        "kg": 1000,

        "milligram": 0.001,
        "milligrams": 0.001,
        "mg": 0.001,

        "pound": 453.59237,
        "pounds": 453.59237,
        "lb": 453.59237
    }

    if (
        from_unit in weight_units
        and to_unit in weight_units
    ):

        grams = (
            value * weight_units[from_unit]
        )

        result = (
            grams / weight_units[to_unit]
        )

        return {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": result
        }

    return {
        "error": (
            f"Conversion from "
            f"{from_unit} to {to_unit} "
            f"is not supported."
        )
    }


# =========================================================
# 5. DATE CALCULATOR
# =========================================================

def date_calculator(
    start_date: str,
    end_date: str
) -> dict:

    try:

        start = datetime.strptime(
            start_date,
            "%Y-%m-%d"
        ).date()

        end = datetime.strptime(
            end_date,
            "%Y-%m-%d"
        ).date()

        difference = abs(
            (end - start).days
        )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "days": difference
        }

    except ValueError:

        return {
            "error": (
                "Invalid date format. "
                "Use YYYY-MM-DD."
            )
        }


# =========================================================
# 6. WEB SEARCH
# =========================================================
#
# Uses DuckDuckGo Instant Answer API.
#
# Note:
# This API is not a complete Google-like web search API.
# It may return no results for some news/current queries.
# =========================================================

def web_search(query: str) -> dict:

    try:

        url = (
            "https://api.duckduckgo.com/"
        )

        response = requests.get(
            url,
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
                "no_redirect": 1
            },
            headers={
                "User-Agent": "ToolMind-AI/1.0"
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        results = []

        # ---------------------------------------------
        # Abstract
        # ---------------------------------------------

        if data.get("AbstractText"):

            results.append({
                "title": data.get(
                    "Heading",
                    query
                ),
                "url": data.get(
                    "AbstractURL",
                    ""
                ),
                "snippet": data.get(
                    "AbstractText",
                    ""
                )
            })


        # ---------------------------------------------
        # Related Topics
        # ---------------------------------------------

        for item in data.get(
            "RelatedTopics",
            []
        ):

            if len(results) >= 5:
                break

            # Normal result
            if (
                isinstance(item, dict)
                and item.get("Text")
            ):

                results.append({
                    "title": item.get(
                        "Text",
                        ""
                    )[:120],

                    "url": item.get(
                        "FirstURL",
                        ""
                    ),

                    "snippet": item.get(
                        "Text",
                        ""
                    )
                })

            # Nested topics
            elif (
                isinstance(item, dict)
                and item.get("Topics")
            ):

                for sub_item in item[
                    "Topics"
                ]:

                    if len(results) >= 5:
                        break

                    if (
                        isinstance(
                            sub_item,
                            dict
                        )
                        and sub_item.get("Text")
                    ):

                        results.append({
                            "title": sub_item.get(
                                "Text",
                                ""
                            )[:120],

                            "url": sub_item.get(
                                "FirstURL",
                                ""
                            ),

                            "snippet": sub_item.get(
                                "Text",
                                ""
                            )
                        })


        print(
            f"Web Search Query: {query}"
        )

        print(
            f"Results Found: {len(results)}"
        )

        return {
            "query": query,
            "results": results
        }


    except Exception as e:

        print(
            "WEB SEARCH ERROR:",
            e
        )

        return {
            "error": str(e)
        }


# =========================================================
# DIRECT TOOL ROUTER
# =========================================================

def direct_tool_router(message):

    text = message.lower().strip()


    # =====================================================
    # 1. DATE CALCULATOR
    # =====================================================

    date_matches = re.findall(
        r"\b\d{4}-\d{2}-\d{2}\b",
        text
    )

    if (
        len(date_matches) >= 2
        and (
            "days between" in text
            or "difference between" in text
            or "days from" in text
            or "how many days" in text
        )
    ):

        result = date_calculator(
            date_matches[0],
            date_matches[1]
        )

        if "error" in result:

            return (
                f"📅 **Date Calculator Error:** "
                f"{result['error']}"
            )

        log_tool(
            "Date Calculator",
            (
                f"{date_matches[0]} "
                f"→ "
                f"{date_matches[1]}"
            )
        )

        return (
            f"📅 **Date Difference:** "
            f"**{result['days']} days**"
        )


    # =====================================================
    # 2. WEATHER
    # =====================================================

    weather_match = re.search(
        r"(?:weather|temperature)"
        r".*?"
        r"(?:in|at|for)\s+"
        r"([a-zA-Z .]+)",
        text
    )

    if weather_match:

        city = weather_match.group(1).strip()

        city = re.sub(
            r"\s+(today|now|currently)$",
            "",
            city
        ).strip()

        result = weather_tool(city)

        if "error" in result:

            return (
                f"🌦️ **Weather Error:** "
                f"{result['error']}"
            )

        log_tool(
            "Weather",
            f"Weather for {result['city']}"
        )

        return (
            f"🌤️ **Weather in "
            f"{result['city']}, "
            f"{result['country']}**\n\n"

            f"🌡️ Temperature: "
            f"{result['temperature']}°C\n"

            f"💧 Humidity: "
            f"{result['humidity']}%\n"

            f"💨 Wind Speed: "
            f"{result['wind_speed']} km/h"
        )


    # =====================================================
    # 3. DATE & TIME
    # =====================================================

    datetime_keywords = [

        "current time",

        "what time is it",

        "current date",

        "what date is it",

        "date and time",

        "date & time",

        "today's date",

        "today date"
    ]

    if any(
        keyword in text
        for keyword in datetime_keywords
    ):

        result = datetime_tool()

        log_tool(
            "Date & Time",
            "Current date and time"
        )

        return (
            f"🕒 **Current Date & Time**\n\n"

            f"📅 Date: "
            f"{result['date']}\n"

            f"📆 Day: "
            f"{result['day']}\n"

            f"⏰ Time: "
            f"{result['time']}"
        )


    # =====================================================
    # 4. UNIT CONVERTER
    # =====================================================

    unit_match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*"
        r"(km|kilometers?|m|meters?|"
        r"cm|centimeters?|mi|miles?|"
        r"ft|feet|kg|kilograms?|"
        r"g|grams?|mg|milligrams?|"
        r"lb|pounds?)"
        r"\s*(?:to|in|into)\s*"
        r"(km|kilometers?|m|meters?|"
        r"cm|centimeters?|mi|miles?|"
        r"ft|feet|kg|kilograms?|"
        r"g|grams?|mg|milligrams?|"
        r"lb|pounds?)",
        text
    )

    if unit_match:

        value = float(
            unit_match.group(1)
        )

        from_unit = unit_match.group(2)
        to_unit = unit_match.group(3)

        result = unit_converter(
            value,
            from_unit,
            to_unit
        )

        if "error" in result:

            return (
                f"📏 **Conversion Error:** "
                f"{result['error']}"
            )

        log_tool(
            "Unit Converter",
            (
                f"{value} "
                f"{from_unit} "
                f"→ "
                f"{to_unit}"
            )
        )

        return (
            f"📏 **Unit Conversion**\n\n"
            f"{value} {from_unit} = "
            f"**{result['result']} "
            f"{to_unit}**"
        )


    # =====================================================
    # 5. CALCULATOR
    # =====================================================

    calculator_match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*"
        r"([+\-*/x×])\s*"
        r"(-?\d+(?:\.\d+)?)",
        text
    )

    if calculator_match:

        a = float(
            calculator_match.group(1)
        )

        operator = (
            calculator_match.group(2)
        )

        b = float(
            calculator_match.group(3)
        )

        if operator == "+":

            result = calculator(
                a,
                b,
                "add"
            )

        elif operator == "-":

            result = calculator(
                a,
                b,
                "subtract"
            )

        elif operator in [
            "x",
            "×",
            "*"
        ]:

            result = calculator(
                a,
                b,
                "multiply"
            )

        elif operator == "/":

            if b == 0:

                return (
                    "🧮 **Calculator Error:** "
                    "Cannot divide by zero."
                )

            result = calculator(
                a,
                b,
                "divide"
            )

        else:

            return None

        if (
            isinstance(result, float)
            and result.is_integer()
        ):

            result = int(result)

        log_tool(
            "Calculator",
            f"{a} {operator} {b}"
        )

        return (
            f"🧮 **Calculator Result:** "
            f"{result}"
        )


    # =====================================================
    # 6. WEB SEARCH
    # =====================================================

    search_patterns = [

        r"^search\s+for\s+(.+)$",

        r"^search\s+latest\s+(.+)$",

        r"^search\s+online\s+(.+)$",

        r"^search\s+web\s+(.+)$",

        r"^web\s+search\s+(.+)$",

        r"^google\s+search\s+(.+)$"
    ]

    query = None

    for pattern in search_patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            query = (
                match.group(1)
                .strip()
                .rstrip("?")
                .strip()
            )

            break


    if query:

        result = web_search(
            query
        )

        if "error" in result:

            return (
                f"🔎 **Search Error:** "
                f"{result['error']}"
            )

        log_tool(
            "Web Search",
            query
        )

        if not result["results"]:

            return (
                f"🔎 No results found for "
                f"**{query}**.\n\n"

                f"Try:\n"
                f"• search for Python programming\n"
                f"• search for Gemini API\n"
                f"• search for Flask framework"
            )

        output = (
            f"🔎 **Web Search Results**\n\n"
            f"Search: **{query}**\n\n"
        )

        for index, item in enumerate(
            result["results"],
            1
        ):

            output += (
                f"**{index}. "
                f"{item['title']}**\n"
            )

            if item["snippet"]:

                output += (
                    f"{item['snippet']}\n"
                )

            if item["url"]:

                output += (
                    f"🔗 {item['url']}\n"
                )

            output += "\n"

        return output


    # =====================================================
    # NO DIRECT TOOL
    # =====================================================

    return None


# =========================================================
# GEMINI CHAT
# =========================================================

def create_chat():

    return client.chats.create(

        model=GEMINI_MODEL,

        config={
            "tools": [
                calculator,
                weather_tool,
                datetime_tool,
                unit_converter,
                date_calculator,
                web_search
            ]
        }
    )


chat = create_chat()


# =========================================================
# SEND TO GEMINI
# =========================================================

def send_to_gemini(
    user_message
):

    global chat

    max_retries = 4

    for attempt in range(
        max_retries
    ):

        try:

            response = chat.send_message(
                user_message
            )

            return response.text

        except errors.ServerError as e:

            if (
                attempt
                == max_retries - 1
            ):

                raise e

            wait_time = (
                2 ** attempt
            )

            print(
                "Gemini server busy. "
                f"Retrying in "
                f"{wait_time} seconds..."
            )

            time.sleep(
                wait_time
            )

        except errors.ClientError as e:

            error_text = str(e)

            if "429" in error_text:

                raise RuntimeError(
                    "QUOTA_EXCEEDED"
                )

            raise e


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# CHAT API
# =========================================================

@app.route(
    "/chat",
    methods=["POST"]
)
def chat_api():

    try:

        data = request.get_json()

        user_message = data.get(
            "message",
            ""
        ).strip()

        if not user_message:

            return jsonify({
                "success": False,
                "error": "Please enter a message."
            }), 400


        # DIRECT TOOL FIRST

        direct_answer = (
            direct_tool_router(
                user_message
            )
        )

        if direct_answer is not None:

            return jsonify({

                "success": True,

                "response": direct_answer,

                "mode": "direct_tool"

            })


        # GEMINI FALLBACK

        answer = send_to_gemini(
            user_message
        )

        return jsonify({

            "success": True,

            "response": answer,

            "mode": "gemini"

        })


    except RuntimeError as e:

        if (
            str(e)
            == "QUOTA_EXCEEDED"
        ):

            return jsonify({

                "success": False,

                "error": (
                    "Gemini API quota has "
                    "been exhausted. "
                    "Direct tools can still "
                    "work."
                )

            }), 429


        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


    except errors.ServerError:

        return jsonify({

            "success": False,

            "error": (
                "Gemini server is "
                "temporarily busy. "
                "Please try again."
            )

        }), 503


    except Exception as e:

        print(
            "ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# =========================================================
# TOOL HISTORY
# =========================================================

@app.route(
    "/tool-history",
    methods=["GET"]
)
def get_tool_history():

    with history_lock:

        return jsonify(
            tool_history
        )


# =========================================================
# CLEAR HISTORY
# =========================================================

@app.route(
    "/clear-history",
    methods=["POST"]
)
def clear_history():

    with history_lock:

        tool_history.clear()

    return jsonify({
        "success": True
    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({

        "status": "ok",

        "model": GEMINI_MODEL,

        "tools": [
            "Calculator",
            "Weather",
            "Date & Time",
            "Unit Converter",
            "Date Calculator",
            "Web Search"
        ]

    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )