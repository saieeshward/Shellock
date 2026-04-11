"""Predefined environment templates for common Python use cases.

Each template has:
    label    — human-readable name
    keywords — phrases that indicate this use case
    packages — list of {name, reason} dicts
"""

from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "ml": {
        "label": "Machine Learning / Deep Learning",
        "keywords": [
            "machine learning", "deep learning", "ml", "neural network",
            "model training", "ai model", "pytorch", "tensorflow", "keras",
            "classification", "regression", "computer science ai",
        ],
        "packages": [
            {"name": "torch", "reason": "primary deep learning framework for model training"},
            {"name": "scikit-learn", "reason": "classical ML algorithms and evaluation utilities"},
            {"name": "pandas", "reason": "data loading, cleaning, and feature preparation"},
            {"name": "numpy", "reason": "numerical operations and array handling"},
            {"name": "jupyter", "reason": "interactive notebook environment for experimentation"},
            {"name": "mlflow", "reason": "experiment tracking and model versioning"},
            {"name": "matplotlib", "reason": "training curve and metric visualisation"},
        ],
    },
    "django": {
        "label": "Web Development (Django)",
        "keywords": [
            "django", "django rest", "drf", "django project", "django app",
            "django api", "django web",
        ],
        "packages": [
            {"name": "django", "reason": "core web framework"},
            {"name": "psycopg2-binary", "reason": "PostgreSQL database driver"},
            {"name": "djangorestframework", "reason": "REST API layer for Django"},
            {"name": "celery", "reason": "background task and job queue processing"},
            {"name": "redis", "reason": "Celery broker and caching backend"},
            {"name": "gunicorn", "reason": "production WSGI server"},
            {"name": "channels", "reason": "WebSocket and async support for Django"},
            {"name": "django-allauth", "reason": "authentication, registration, and social login"},
        ],
    },
    "flask_fastapi": {
        "label": "Web Development (Flask / FastAPI)",
        "keywords": [
            "flask", "fastapi", "rest api", "web api", "api server",
            "http api", "microservice", "web service", "api backend",
            "web development", "web app", "web application", "website", "web dev",
        ],
        "packages": [
            {"name": "fastapi", "reason": "high-performance async web framework"},
            {"name": "uvicorn", "reason": "ASGI server to run FastAPI"},
            {"name": "sqlalchemy", "reason": "ORM for database access"},
            {"name": "pydantic", "reason": "request/response validation and serialisation"},
            {"name": "python-jose", "reason": "JWT authentication token handling"},
            {"name": "httpx", "reason": "async HTTP client for calling external services"},
            {"name": "alembic", "reason": "database schema migration management"},
        ],
    },
    "data_engineering": {
        "label": "Data Engineering / ETL",
        "keywords": [
            "etl", "data pipeline", "data engineering", "airflow", "spark",
            "pyspark", "data warehouse", "data lake", "pipeline", "ingestion",
            "batch processing", "streaming",
        ],
        "packages": [
            {"name": "apache-airflow", "reason": "workflow orchestration for pipeline scheduling"},
            {"name": "pyspark", "reason": "distributed data processing at scale"},
            {"name": "pandas", "reason": "in-memory data transformation and cleaning"},
            {"name": "sqlalchemy", "reason": "unified interface to relational databases"},
            {"name": "psycopg2-binary", "reason": "PostgreSQL connector"},
            {"name": "pymongo", "reason": "MongoDB connector for NoSQL storage"},
            {"name": "boto3", "reason": "AWS S3 and cloud service integration"},
            {"name": "google-cloud-storage", "reason": "GCP cloud storage access"},
            {"name": "great-expectations", "reason": "data quality validation and profiling"},
        ],
    },
    "data_science": {
        "label": "Data Science / Analytics",
        "keywords": [
            "data science", "analytics", "data analysis", "visualization",
            "statistics", "statistical", "exploratory", "eda", "notebook",
            "data exploration", "insight",
        ],
        "packages": [
            {"name": "pandas", "reason": "core data manipulation and analysis library"},
            {"name": "numpy", "reason": "numerical computing and array operations"},
            {"name": "matplotlib", "reason": "static chart and plot generation"},
            {"name": "seaborn", "reason": "statistical data visualisation built on matplotlib"},
            {"name": "plotly", "reason": "interactive charts and dashboards"},
            {"name": "scipy", "reason": "scientific and statistical computations"},
            {"name": "statsmodels", "reason": "statistical models and hypothesis testing"},
            {"name": "jupyter", "reason": "interactive notebook environment"},
            {"name": "sqlalchemy", "reason": "SQL database querying from notebooks"},
        ],
    },
    "scraping": {
        "label": "Web Scraping / Crawling",
        "keywords": [
            "scraping", "crawling", "scraper", "crawler", "web scraping",
            "data extraction", "spider", "beautifulsoup", "scrapy", "selenium",
            "playwright", "browser automation",
        ],
        "packages": [
            {"name": "scrapy", "reason": "full-featured crawling framework for managing spiders and pipelines"},
            {"name": "beautifulsoup4", "reason": "HTML parsing and structured data extraction from pages"},
            {"name": "playwright", "reason": "headless browser automation for JavaScript-rendered pages"},
            {"name": "requests", "reason": "simple HTTP client for fetching pages"},
            {"name": "lxml", "reason": "fast XML/HTML parser used by BeautifulSoup"},
            {"name": "fake-useragent", "reason": "rotating user-agent headers to avoid blocking"},
        ],
    },
    "api_microservices": {
        "label": "API Development / Microservices",
        "keywords": [
            "microservice", "microservices", "service mesh", "api gateway",
            "distributed", "async api", "event driven", "message queue",
        ],
        "packages": [
            {"name": "fastapi", "reason": "async-native framework for high-throughput APIs"},
            {"name": "aiohttp", "reason": "async HTTP client/server for service-to-service calls"},
            {"name": "pydantic", "reason": "strict request/response schema validation"},
            {"name": "redis", "reason": "pub/sub messaging and shared cache between services"},
            {"name": "celery", "reason": "distributed task queue for background jobs"},
            {"name": "httpx", "reason": "async HTTP client with retry and timeout support"},
            {"name": "opentelemetry-sdk", "reason": "distributed tracing across services"},
        ],
    },
    "devops": {
        "label": "DevOps / Infrastructure Automation",
        "keywords": [
            "devops", "infrastructure", "automation", "deployment", "ansible",
            "terraform", "kubernetes", "docker", "ci cd", "provisioning",
            "cloud", "ops",
        ],
        "packages": [
            {"name": "ansible", "reason": "agentless infrastructure configuration and automation"},
            {"name": "fabric", "reason": "SSH-based remote command execution and deployment"},
            {"name": "paramiko", "reason": "SSH protocol implementation for remote access"},
            {"name": "boto3", "reason": "AWS SDK for cloud resource management"},
            {"name": "google-cloud", "reason": "GCP SDK for cloud operations"},
            {"name": "docker", "reason": "Docker daemon API client for container management"},
            {"name": "kubernetes", "reason": "Kubernetes API client for cluster management"},
        ],
    },
    "testing": {
        "label": "Testing / QA Automation",
        "keywords": [
            "testing", "qa", "quality assurance", "test automation", "unit test",
            "integration test", "e2e", "end to end", "load test", "test suite",
        ],
        "packages": [
            {"name": "pytest", "reason": "primary test runner and assertion framework"},
            {"name": "coverage", "reason": "code coverage measurement and reporting"},
            {"name": "playwright", "reason": "end-to-end browser testing"},
            {"name": "httpx", "reason": "API testing with async HTTP client"},
            {"name": "hypothesis", "reason": "property-based testing to find edge cases"},
            {"name": "locust", "reason": "load and performance testing"},
            {"name": "factory-boy", "reason": "test fixture generation"},
        ],
    },
    "scientific": {
        "label": "Scientific Computing / Research",
        "keywords": [
            "scientific", "research", "simulation", "numerical", "physics",
            "biology", "chemistry", "math", "symbolic", "computation",
            "bioinformatics", "astronomy",
        ],
        "packages": [
            {"name": "numpy", "reason": "foundation for numerical array computation"},
            {"name": "scipy", "reason": "scientific algorithms: integration, optimisation, signal processing"},
            {"name": "sympy", "reason": "symbolic mathematics and algebraic computation"},
            {"name": "matplotlib", "reason": "publication-quality scientific plotting"},
            {"name": "jupyter", "reason": "reproducible research notebook environment"},
            {"name": "pandas", "reason": "tabular data handling and experimental result storage"},
        ],
    },
    "cli": {
        "label": "CLI Tools / Terminal Applications",
        "keywords": [
            "cli", "command line", "terminal", "command-line tool", "shell tool",
            "tui", "terminal ui", "terminal application", "console app",
        ],
        "packages": [
            {"name": "typer", "reason": "CLI framework with automatic help and type hints"},
            {"name": "rich", "reason": "rich text, tables, progress bars, and syntax highlighting in terminal"},
            {"name": "prompt-toolkit", "reason": "interactive prompts and auto-completion"},
            {"name": "colorama", "reason": "cross-platform terminal colour support"},
            {"name": "pyyaml", "reason": "YAML configuration file parsing"},
            {"name": "tomllib", "reason": "TOML configuration file parsing"},
        ],
    },
    "computer_vision": {
        "label": "Computer Vision",
        "keywords": [
            "computer vision", "image processing", "object detection", "image recognition",
            "ocr", "face detection", "video processing", "image classification",
            "segmentation", "vision model",
        ],
        "packages": [
            {"name": "opencv-python", "reason": "core computer vision and image processing library"},
            {"name": "pillow", "reason": "image loading, transformation, and saving"},
            {"name": "scikit-image", "reason": "image processing algorithms and filters"},
            {"name": "albumentations", "reason": "fast image augmentation for training datasets"},
            {"name": "pytesseract", "reason": "OCR text extraction from images"},
            {"name": "torch", "reason": "deep learning backbone for vision models"},
            {"name": "torchvision", "reason": "pretrained vision models and dataset utilities"},
        ],
    },
    "nlp": {
        "label": "NLP / Text Processing",
        "keywords": [
            "nlp", "natural language", "text processing", "sentiment", "language model",
            "text classification", "named entity", "ner", "tokenization", "chatbot",
            "text generation", "summarization", "translation",
        ],
        "packages": [
            {"name": "transformers", "reason": "Hugging Face pretrained language models (BERT, GPT, etc.)"},
            {"name": "spacy", "reason": "industrial-strength NLP: tokenisation, NER, parsing"},
            {"name": "nltk", "reason": "classic NLP toolkit for text preprocessing"},
            {"name": "gensim", "reason": "topic modelling and word embeddings"},
            {"name": "textblob", "reason": "simple sentiment analysis and text classification"},
            {"name": "datasets", "reason": "Hugging Face dataset loading and processing"},
        ],
    },
    "game": {
        "label": "Game Development / Simulation",
        "keywords": [
            "game", "pygame", "simulation", "gaming", "game engine",
            "physics simulation", "npc", "procedural generation", "2d game", "3d game",
        ],
        "packages": [
            {"name": "pygame", "reason": "2D game development framework with sprites and input handling"},
            {"name": "pyglet", "reason": "windowing, graphics, and audio for games"},
            {"name": "pymunk", "reason": "2D physics engine for realistic game physics"},
            {"name": "noise", "reason": "Perlin noise for procedural terrain generation"},
        ],
    },
    "blockchain": {
        "label": "Blockchain / Crypto Development",
        "keywords": [
            "blockchain", "crypto", "ethereum", "web3", "smart contract",
            "defi", "nft", "wallet", "solidity", "token", "dapp",
        ],
        "packages": [
            {"name": "web3", "reason": "Python interface to Ethereum nodes and smart contracts"},
            {"name": "eth-brownie", "reason": "smart contract development and testing framework"},
            {"name": "py-solc-x", "reason": "Solidity compiler for compiling smart contracts"},
            {"name": "cryptography", "reason": "cryptographic primitives for wallet and key management"},
            {"name": "requests", "reason": "HTTP client for blockchain REST APIs and price feeds"},
        ],
    },
}


def match_template(description: str) -> dict | None:
    """Return the best-matching template for a description, or None.

    Scores each template by how many of its keywords appear in the
    description. Returns the highest-scoring template if it scores
    above the minimum threshold.
    """
    desc_lower = description.lower()
    best_key: str | None = None
    best_score = 0

    for key, tmpl in TEMPLATES.items():
        score = sum(1 for kw in tmpl["keywords"] if kw in desc_lower)
        if score > best_score:
            best_score = score
            best_key = key

    return TEMPLATES[best_key] if best_score >= 1 else None
