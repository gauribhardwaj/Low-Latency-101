import os
import requests
import logging

# Set up logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logger.debug("📢 Logger is working inside gpt_review.py")  


def query_llm_with_code(code, language):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("❌ API key missing.")
        return "❌ API key missing. Please set OPENROUTER_API_KEY in your .env file."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://low-latency-101.streamlit.app",
        "X-Title": "Low Latency Runbook"
    }

    prompt = f"""You're a senior performance engineer.

Please review the following {language} code for latency-related bottlenecks:
- GC pressure
- memory allocation in hot loops
- I/O in tight paths
- branch misprediction
- data layout
- thread contention

Explain each problem in plain language, suggest fixes, and if possible, rewrite the code with improvements.

Code:
```{language.lower()}
{code}
```"""

    body = {
        "model": "deepseek/deepseek-chat-v3-0324",
        "messages": [
            {"role": "system", "content": "You're a low-latency code reviewer."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        logger.info("📤 Sending request to OpenRouter...")
        logger.debug(f"Endpoint: https://openrouter.ai/api/v1/chat/completions")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Payload: {body}")

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
        logger.debug(f"Response Status Code: {response.status_code}")
        logger.debug(f"Response Text: {response.text}")

        # Try to parse JSON only if response body exists
        if response.text.strip() == "":
            logger.error("❌ Empty response body received from OpenRouter.")
            return "❌ Error: Empty response from OpenRouter."

        content = response.json()["choices"][0]["message"]["content"]
        logger.info("✅ GPT response parsed successfully.")
        return content

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"❌ HTTP error occurred: {http_err}")
        return f"❌ HTTP error: {http_err}"

    except requests.exceptions.RequestException as req_err:
        logger.error(f"❌ Request error: {req_err}")
        return f"❌ Request error: {req_err}"

    except Exception as e:
        logger.exception("❌ Unexpected error while handling GPT response")
        return f"❌ Error calling OpenRouter: {e}"
