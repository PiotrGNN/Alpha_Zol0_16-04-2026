# LLMAuditor.py – sanity-check decyzji AI przez LLM
import logging


class LLMAuditor:
    def __init__(self, llm=None):
        self.llm = llm  # np. lokalny GPT

    def audit(self, strategy_input, strategy_output, portfolio_state=None):
        # Real LLM audit integration (e.g., OpenAI GPT-4-turbo)
        if self.llm:
            prompt = (
                f"AUDYT DECYZJI AI\n"
                f"Stan portfela: {portfolio_state}\n"
                f"Strategia: {strategy_input}\n"
                f"Decyzja: {strategy_output}\n"
                f"Wyjaśnij dlaczego została podjęta decyzja X."
            )
            result = self.llm(prompt)
            logging.info(f"LLMAuditor: LLM result: {result}")
            return result
        # Fallback: heurystyka
        if "error" in str(strategy_output).lower():
            logging.warning("LLMAuditor: output contains error")
            return False
        return True

    def connect_openai(self, api_key):
        # Example: connect to OpenAI GPT-4-turbo
        import openai

        openai.api_key = api_key
        self.llm = lambda prompt: openai.ChatCompletion.create(
            model="gpt-4-turbo", messages=[{"role": "user", "content": prompt}]
        )["choices"][0]["message"]["content"]
