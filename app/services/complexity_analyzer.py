import re
import json
from typing import Dict, Tuple
from app.core.config import settings
from app.core.logger import logger
from app.models.schema import ComplexityAnalysis
import requests

class ComplexityAnalyzer:

    def __init__(self):
        self.ollama_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT

    def analyze(self, prompt: str) -> ComplexityAnalysis:
        try:
            local_score = self._local_heuristic_score(prompt)

            ollama_score = self._ollama_assessment(prompt)

            final_score = (local_score + ollama_score) / 2

            if final_score < 33:
                level = "simple"
                reasoning = "Query can be handled by local model"
            elif final_score < 66:
                level = "medium"
                reasoning = "Query has moderate complexity"
            else:
                level = "difficult"
                reasoning = "Query requires advanced model"

            return ComplexityAnalysis(
                level=level,
                score=final_score,
                reasoning=reasoning,
                confidence=0.85,
            )
        except Exception as e:
            logger.error(f"Error analyzing complexity: {e}")
            return ComplexityAnalysis(
                level="medium",
                score=50.0,
                reasoning="Error in analysis, defaulting to medium",
                confidence=0.5,
            )

    def _local_heuristic_score(self, prompt: str) -> float:
        score = 0

        words = len(prompt.split())
        if words < 20:
            score += 10
        elif words < 50:
            score += 20
        elif words < 100:
            score += 30
        else:
            score += 40

        technical_terms = [
            "algorithm",
            "optimization",
            "machine learning",
            "neural network",
            "regex",
            "api",
            "database",
            "architecture",
            "scalability",
            "performance",
        ]
        technical_count = sum(
            1 for term in technical_terms if term.lower() in prompt.lower()
        )
        score += min(technical_count * 5, 30)

        math_indicators = [
            "calculate",
            "compute",
            "derive",
            "equation",
            "formula",
            "probability",
        ]
        math_count = sum(1 for term in math_indicators if term in prompt.lower())
        score += min(math_count * 5, 20)

        return min(score, 100)

    def _ollama_assessment(self, prompt: str) -> float:
        try:
            assessment_prompt = f"""Analyze the complexity of this query on a scale of 0-100:
Query: {prompt}

Provide only a JSON response with 'complexity_score' (0-100):"""

            print (f"ollama_url:", self.ollama_url)
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": assessment_prompt,
                    "stream": False,
                },
                timeout=(settings.OLLAMA_CONNECT_TIMEOUT, self.timeout),
            )

            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")

                try:
                    json_match = re.search(r"\{.*\}", response_text)
                    if json_match:
                        json_data = json.loads(json_match.group())
                        score = json_data.get("complexity_score", 50)
                        return min(max(score, 0), 100)
                except json.JSONDecodeError:
                    pass

            return 50
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
            logger.error(
                f"Cannot reach Ollama at {self.ollama_url} for complexity scoring "
                f"({e.__class__.__name__}); defaulting score to 50. "
                "Check EC2 security group + OLLAMA_HOST=0.0.0.0."
            )
            return 50
        except Exception as e:
            logger.error(f"Error getting Ollama assessment: {e}")
            return 50
