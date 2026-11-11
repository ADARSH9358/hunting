"""Curated technology skill taxonomy with aliases.

Used for deterministic, explainable skill extraction from resumes and job
descriptions. Ambiguous short names (Go, R, React, Spring, Swift, ML, RAG ...)
are matched case-sensitively to avoid false positives from ordinary English.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Skill:
    canonical: str
    category: str
    aliases: tuple[str, ...] = ()
    case_sensitive: tuple[str, ...] = ()  # aliases that must match with exact case
    weight: float = 1.0


def S(canonical, category, aliases=(), cs=(), weight=1.0) -> Skill:
    return Skill(canonical, category, tuple(aliases), tuple(cs), weight)


SKILLS: list[Skill] = [
    # --- languages ---
    S("Python", "language", ["python", "python3"]),
    S("Java", "language", ["java", "java 8", "java 11", "java 17", "core java"]),
    S("JavaScript", "language", ["javascript", "js", "es6", "ecmascript"]),
    S("TypeScript", "language", ["typescript"], cs=["TS"]),
    S("Go", "language", ["golang"], cs=["Go"]),
    S("Rust", "language", ["rust"]),
    S("C", "language", [], cs=["C programming", "C language", "ANSI C"]),
    S("C++", "language", ["c++", "cpp"]),
    S("C#", "language", ["c#", "csharp", "c sharp"]),
    S("Kotlin", "language", ["kotlin"]),
    S("Swift", "language", [], cs=["Swift", "SwiftUI"]),
    S("Ruby", "language", ["ruby"]),
    S("PHP", "language", ["php"]),
    S("Scala", "language", ["scala"]),
    S("R", "language", ["r programming", "rstudio"], cs=["R language"]),
    S("Dart", "language", ["dart"]),
    S("SQL", "language", ["sql", "t-sql", "pl/sql", "plsql"]),
    S("Bash", "language", ["bash", "shell scripting", "shell script"], weight=0.5),
    S("HTML", "language", ["html", "html5"], weight=0.6),
    S("CSS", "language", ["css", "css3", "scss", "sass"], weight=0.6),
    S("Solidity", "language", ["solidity"]),
    S("Elixir", "language", ["elixir"]),
    S("Perl", "language", ["perl"]),
    # --- frameworks / libraries ---
    S("Node.js", "framework", ["node.js", "nodejs", "node js"], cs=["Node"]),
    S("Express.js", "framework", ["express.js", "expressjs", "express js"], cs=["Express"]),
    S("NestJS", "framework", ["nestjs", "nest.js"]),
    S("React", "framework", ["react.js", "reactjs", "react js"], cs=["React"]),
    S("Next.js", "framework", ["next.js", "nextjs"]),
    S("Angular", "framework", ["angular", "angularjs", "angular.js"]),
    S("Vue.js", "framework", ["vue", "vue.js", "vuejs"]),
    S("Svelte", "framework", ["svelte", "sveltekit"]),
    S("Redux", "framework", ["redux"]),
    S("Tailwind CSS", "framework", ["tailwind", "tailwindcss", "tailwind css"], weight=0.6),
    S("Django", "framework", ["django"]),
    S("Flask", "framework", ["flask"]),
    S("FastAPI", "framework", ["fastapi", "fast api"]),
    S("Spring Boot", "framework", ["spring boot", "springboot", "spring framework", "spring mvc"], cs=["Spring"]),
    S("Hibernate", "framework", ["hibernate", "jpa"]),
    S(".NET", "framework", [".net", "dotnet", ".net core", "asp.net", "asp.net core"]),
    S("Ruby on Rails", "framework", ["ruby on rails", "ror"], cs=["Rails"]),
    S("Laravel", "framework", ["laravel"]),
    S("React Native", "mobile", ["react native", "react-native"]),
    S("Flutter", "mobile", ["flutter"]),
    S("Android", "mobile", ["android"]),
    S("iOS", "mobile", [], cs=["iOS"]),
    S("GraphQL", "framework", ["graphql"]),
    S("gRPC", "framework", ["grpc"]),
    S("jQuery", "framework", ["jquery"], weight=0.5),
    S("Celery", "framework", ["celery"]),
    S("Pydantic", "framework", ["pydantic"], weight=0.6),
    S("SQLAlchemy", "framework", ["sqlalchemy"], weight=0.7),
    # --- databases ---
    S("PostgreSQL", "database", ["postgresql", "postgres", "psql"]),
    S("MySQL", "database", ["mysql"]),
    S("MongoDB", "database", ["mongodb", "mongo db", "mongoose"], cs=["Mongo"]),
    S("Redis", "database", ["redis"]),
    S("SQLite", "database", ["sqlite"], weight=0.5),
    S("Oracle Database", "database", ["oracle db", "oracle database", "oracle sql"]),
    S("SQL Server", "database", ["sql server", "mssql", "ms sql"]),
    S("Cassandra", "database", ["cassandra"]),
    S("DynamoDB", "database", ["dynamodb"]),
    S("Elasticsearch", "database", ["elasticsearch", "elastic search", "opensearch"]),
    S("Firebase", "database", ["firebase", "firestore"]),
    S("Supabase", "database", ["supabase"]),
    S("Neo4j", "database", ["neo4j"]),
    S("Snowflake", "data", ["snowflake"]),
    S("BigQuery", "data", ["bigquery", "big query"]),
    S("Redshift", "data", ["redshift"]),
    # --- cloud / devops ---
    S("AWS", "cloud", ["aws", "amazon web services", "ec2", "s3", "aws lambda", "lambda functions"]),
    S("Azure", "cloud", ["azure", "microsoft azure"]),
    S("GCP", "cloud", ["gcp", "google cloud", "google cloud platform"]),
    S("Docker", "devops", ["docker", "containerization", "dockerfile"]),
    S("Kubernetes", "devops", ["kubernetes", "k8s", "eks", "gke", "aks"]),
    S("Terraform", "devops", ["terraform"]),
    S("Ansible", "devops", ["ansible"]),
    S("Jenkins", "devops", ["jenkins"]),
    S("GitHub Actions", "devops", ["github actions"]),
    S("CI/CD", "devops", ["ci/cd", "ci cd", "continuous integration", "continuous delivery", "continuous deployment"]),
    S("Linux", "devops", ["linux", "unix", "ubuntu"], weight=0.5),
    S("Nginx", "devops", ["nginx"], weight=0.6),
    S("Serverless", "cloud", ["serverless"]),
    S("Vercel", "cloud", ["vercel"], weight=0.5),
    S("Heroku", "cloud", ["heroku"], weight=0.5),
    # --- data / messaging ---
    S("Kafka", "data", ["kafka", "apache kafka"]),
    S("RabbitMQ", "data", ["rabbitmq"]),
    S("Apache Spark", "data", ["spark", "pyspark", "apache spark"]),
    S("Hadoop", "data", ["hadoop", "hdfs"]),
    S("Airflow", "data", ["airflow", "apache airflow"]),
    S("dbt", "data", [], cs=["dbt"]),
    S("Databricks", "data", ["databricks"]),
    S("Pandas", "data", ["pandas"]),
    S("NumPy", "data", ["numpy"]),
    S("ETL", "data", ["etl", "elt", "data pipelines", "data pipeline"]),
    S("Tableau", "data", ["tableau"]),
    S("Power BI", "data", ["power bi", "powerbi"]),
    S("Excel", "tool", ["ms excel", "microsoft excel", "advanced excel"], weight=0.4),
    # --- AI / ML ---
    S("Machine Learning", "ai_ml", ["machine learning"], cs=["ML"]),
    S("Deep Learning", "ai_ml", ["deep learning", "neural networks", "neural network"]),
    S("Generative AI", "ai_ml", ["generative ai", "genai", "gen ai", "gen-ai"]),
    S("LLM", "ai_ml", ["large language model", "large language models", "llms", "llm"]),
    S("RAG", "ai_ml", ["retrieval augmented generation", "retrieval-augmented generation"], cs=["RAG"]),
    S("LangChain", "ai_ml", ["langchain", "lang chain"]),
    S("LangGraph", "ai_ml", ["langgraph"]),
    S("LlamaIndex", "ai_ml", ["llamaindex", "llama index", "llama-index"]),
    S("OpenAI API", "ai_ml", ["openai", "gpt-4", "gpt-3.5", "chatgpt api", "gpt api"]),
    S("Anthropic Claude", "ai_ml", ["anthropic", "claude api"]),
    S("Hugging Face", "ai_ml", ["hugging face", "huggingface", "transformers library"]),
    S("Prompt Engineering", "ai_ml", ["prompt engineering", "prompt design"]),
    S("AI Agents", "ai_ml", ["ai agents", "agentic", "autonomous agents", "multi-agent"]),
    S("Vector Databases", "ai_ml", ["vector database", "vector databases", "vector db", "vector store", "embeddings"]),
    S("Pinecone", "ai_ml", ["pinecone"]),
    S("FAISS", "ai_ml", ["faiss"]),
    S("ChromaDB", "ai_ml", ["chromadb", "chroma db"]),
    S("Weaviate", "ai_ml", ["weaviate"]),
    S("pgvector", "ai_ml", ["pgvector"]),
    S("PyTorch", "ai_ml", ["pytorch", "torch"]),
    S("TensorFlow", "ai_ml", ["tensorflow", "keras"]),
    S("scikit-learn", "ai_ml", ["scikit-learn", "sklearn", "scikit learn"]),
    S("NLP", "ai_ml", ["natural language processing", "nlp"]),
    S("Computer Vision", "ai_ml", ["computer vision", "opencv", "image processing"]),
    S("MLOps", "ai_ml", ["mlops", "ml ops"]),
    S("MLflow", "ai_ml", ["mlflow"]),
    S("Fine-tuning", "ai_ml", ["fine-tuning", "fine tuning", "finetuning", "lora", "peft"]),
    S("Data Science", "ai_ml", ["data science"]),
    S("Statistics", "ai_ml", ["statistics", "statistical analysis"], weight=0.6),
    # --- concepts / practices ---
    S("REST APIs", "concept", ["rest api", "rest apis", "restful", "restful apis", "restful api", "rest services"], cs=["REST"]),
    S("Microservices", "concept", ["microservices", "microservice", "micro-services"]),
    S("System Design", "concept", ["system design", "distributed systems", "scalable systems"]),
    S("Data Structures & Algorithms", "concept", ["data structures", "algorithms", "dsa"], weight=0.6),
    S("OOP", "concept", ["object oriented", "object-oriented", "oops", "oop"], weight=0.5),
    S("Web Sockets", "concept", ["websocket", "websockets", "socket.io"]),
    S("Unit Testing", "testing", ["unit testing", "unit tests", "tdd", "test driven"], weight=0.6),
    S("Pytest", "testing", ["pytest"], weight=0.6),
    S("Jest", "testing", ["jest"], weight=0.6),
    S("Selenium", "testing", ["selenium"]),
    S("Playwright", "testing", ["playwright"]),
    S("Cypress", "testing", ["cypress"]),
    S("Git", "tool", ["git", "github", "gitlab", "bitbucket"], weight=0.4),
    S("Jira", "tool", ["jira"], weight=0.3),
    S("Agile", "concept", ["agile", "scrum", "kanban"], weight=0.3),
    S("Postman", "tool", ["postman"], weight=0.4),
    S("Figma", "tool", ["figma"], weight=0.5),
    S("Web Scraping", "data", ["web scraping", "beautifulsoup", "scrapy", "web crawling"]),
    S("Blockchain", "concept", ["blockchain", "web3", "ethereum"]),
    S("Cybersecurity", "concept", ["cybersecurity", "cyber security", "information security", "owasp"]),
    S("OAuth", "concept", ["oauth", "oauth2", "jwt", "openid connect"], weight=0.6),
    S("Salesforce", "tool", ["salesforce", "apex"]),
    S("SAP", "tool", [], cs=["SAP"]),
]

SKILL_BY_CANONICAL: dict[str, Skill] = {s.canonical.lower(): s for s in SKILLS}


def _boundary(alias: str) -> str:
    return r"(?<![A-Za-z0-9+#.])" + re.escape(alias) + r"(?![A-Za-z0-9+#]|\.[A-Za-z0-9])"


@lru_cache
def _compiled() -> list[tuple[Skill, re.Pattern | None, re.Pattern | None]]:
    out = []
    for s in SKILLS:
        ci_aliases = {a.lower() for a in s.aliases}
        if s.canonical.lower() not in {c.lower() for c in s.case_sensitive} and len(s.canonical) > 2:
            ci_aliases.add(s.canonical.lower())
        ci = re.compile("|".join(_boundary(a) for a in sorted(ci_aliases, key=len, reverse=True)), re.I) if ci_aliases else None
        cs = re.compile("|".join(_boundary(a) for a in s.case_sensitive)) if s.case_sensitive else None
        out.append((s, ci, cs))
    return out


def extract_skills(text: str) -> list[Skill]:
    """Return skills explicitly present in ``text`` (never inferred)."""
    if not text:
        return []
    found: list[Skill] = []
    for skill, ci, cs in _compiled():
        if (ci and ci.search(text)) or (cs and cs.search(text)):
            found.append(skill)
    return found


def canonicalize(name: str) -> Skill | None:
    """Map a free-form skill name (e.g. from an LLM or user edit) to the taxonomy."""
    if not name:
        return None
    key = name.strip().lower()
    if key in SKILL_BY_CANONICAL:
        return SKILL_BY_CANONICAL[key]
    for s in SKILLS:
        if key in {a.lower() for a in s.aliases} or key in {c.lower() for c in s.case_sensitive}:
            return s
    hits = extract_skills(name)
    return hits[0] if len(hits) == 1 else None


def canonical_name(name: str) -> str:
    s = canonicalize(name)
    return s.canonical if s else name.strip()


def category_of(name: str) -> str:
    s = canonicalize(name)
    return s.category if s else "other"


def weight_of(name: str) -> float:
    s = canonicalize(name)
    return s.weight if s else 0.8


def skill_in_text(name: str, text: str) -> bool:
    """True if the skill (or one of its aliases) literally appears in text."""
    s = canonicalize(name)
    if s:
        return any(x.canonical == s.canonical for x in extract_skills(text))
    return bool(re.search(_boundary(name.strip()), text, re.I))
