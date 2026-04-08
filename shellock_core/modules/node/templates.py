"""Predefined environment templates for common Node.js use cases.

Each template has:
    label    — human-readable name
    keywords — phrases that indicate this use case
    packages — list of {name, reason} dicts
"""

from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "react": {
        "label": "Frontend Development (React)",
        "keywords": [
            "react", "react app", "react frontend", "create react app",
            "react typescript", "react project", "react ui",
        ],
        "packages": [
            {"name": "react", "reason": "core React library for building UI components"},
            {"name": "react-dom", "reason": "DOM rendering for React"},
            {"name": "next", "reason": "React framework with SSR, routing, and API routes"},
            {"name": "typescript", "reason": "static typing for safer, more maintainable React code"},
            {"name": "tailwindcss", "reason": "utility-first CSS framework for rapid styling"},
            {"name": "react-hook-form", "reason": "performant form state management and validation"},
            {"name": "zustand", "reason": "lightweight client state management"},
            {"name": "jest", "reason": "unit and component testing"},
            {"name": "@testing-library/react", "reason": "component testing utilities focused on user behaviour"},
        ],
    },
    "vue": {
        "label": "Frontend Development (Vue)",
        "keywords": [
            "vue", "vue 3", "vue.js", "vuejs", "nuxt", "nuxt.js",
            "vue frontend", "vue project", "vue app",
        ],
        "packages": [
            {"name": "vue", "reason": "core Vue 3 framework"},
            {"name": "nuxt", "reason": "Vue meta-framework with SSR and file-based routing"},
            {"name": "typescript", "reason": "static typing for Vue components"},
            {"name": "pinia", "reason": "official Vue state management store"},
            {"name": "vue-router", "reason": "client-side routing for Vue SPAs"},
            {"name": "vite", "reason": "fast dev server and build tool"},
            {"name": "vitest", "reason": "Vite-native unit testing framework"},
            {"name": "vuetify", "reason": "Material Design component library for Vue"},
        ],
    },
    "express": {
        "label": "Backend API Development (Express)",
        "keywords": [
            "express", "express api", "express backend", "express server",
            "express rest", "node api", "node backend", "node server",
        ],
        "packages": [
            {"name": "express", "reason": "minimal and flexible Node.js web framework"},
            {"name": "typescript", "reason": "static typing for safer backend code"},
            {"name": "prisma", "reason": "type-safe ORM and database migration tool"},
            {"name": "passport", "reason": "authentication middleware supporting many strategies"},
            {"name": "jsonwebtoken", "reason": "JWT creation and verification for auth"},
            {"name": "zod", "reason": "runtime request body validation and type inference"},
            {"name": "winston", "reason": "structured logging with multiple transports"},
            {"name": "cors", "reason": "Cross-Origin Resource Sharing middleware"},
            {"name": "dotenv", "reason": "environment variable loading from .env files"},
        ],
    },
    "nestjs": {
        "label": "Backend API Development (NestJS)",
        "keywords": [
            "nestjs", "nest.js", "nest framework", "nest api",
            "nest backend", "nest project",
        ],
        "packages": [
            {"name": "@nestjs/core", "reason": "NestJS application core"},
            {"name": "@nestjs/common", "reason": "NestJS decorators, pipes, guards, and interceptors"},
            {"name": "@nestjs/platform-express", "reason": "Express adapter for NestJS"},
            {"name": "typescript", "reason": "NestJS is TypeScript-first by design"},
            {"name": "prisma", "reason": "type-safe ORM for database access"},
            {"name": "@nestjs/graphql", "reason": "GraphQL module for NestJS"},
            {"name": "bull", "reason": "Redis-backed job queue for background processing"},
            {"name": "@nestjs/swagger", "reason": "automatic OpenAPI documentation generation"},
        ],
    },
    "fullstack": {
        "label": "Full-Stack Development (MEAN / MERN)",
        "keywords": [
            "mern", "mean", "full stack", "fullstack", "full-stack",
            "mongo express react", "mongo express angular",
        ],
        "packages": [
            {"name": "express", "reason": "backend API server"},
            {"name": "mongoose", "reason": "MongoDB ODM for schema-based data modelling"},
            {"name": "react", "reason": "frontend UI library"},
            {"name": "react-dom", "reason": "DOM rendering for React"},
            {"name": "axios", "reason": "HTTP client for frontend-to-backend API calls"},
            {"name": "jsonwebtoken", "reason": "JWT-based authentication between client and server"},
            {"name": "react-router-dom", "reason": "client-side routing for React"},
            {"name": "dotenv", "reason": "environment variable management"},
        ],
    },
    "realtime": {
        "label": "Real-Time Applications",
        "keywords": [
            "real-time", "realtime", "websocket", "socket", "chat app",
            "live updates", "presence", "pub sub", "push notifications",
            "streaming", "event driven",
        ],
        "packages": [
            {"name": "socket.io", "reason": "WebSocket library for real-time bidirectional communication"},
            {"name": "redis", "reason": "pub/sub broker for broadcasting events across server instances"},
            {"name": "ws", "reason": "lightweight WebSocket implementation"},
            {"name": "express", "reason": "HTTP server to serve the WebSocket upgrade"},
            {"name": "ioredis", "reason": "robust Redis client with cluster support"},
        ],
    },
    "graphql": {
        "label": "GraphQL API Development",
        "keywords": [
            "graphql", "apollo", "gql", "apollo server", "graphql api",
            "graphql backend", "type graphql", "schema",
        ],
        "packages": [
            {"name": "apollo-server", "reason": "production-ready GraphQL server"},
            {"name": "graphql", "reason": "core GraphQL query language runtime"},
            {"name": "type-graphql", "reason": "schema definition using TypeScript decorators"},
            {"name": "dataloader", "reason": "batching and caching to solve the N+1 query problem"},
            {"name": "prisma", "reason": "type-safe database access for resolvers"},
            {"name": "graphql-subscriptions", "reason": "real-time GraphQL subscriptions"},
        ],
    },
    "serverless": {
        "label": "Serverless / Cloud Functions",
        "keywords": [
            "serverless", "lambda", "cloud functions", "faas",
            "aws lambda", "netlify functions", "vercel functions",
            "function as a service",
        ],
        "packages": [
            {"name": "serverless", "reason": "framework for deploying and managing serverless functions"},
            {"name": "@aws-sdk/client-lambda", "reason": "AWS Lambda SDK for invocation and management"},
            {"name": "@aws-sdk/client-s3", "reason": "AWS S3 SDK for object storage access"},
            {"name": "dotenv", "reason": "environment variable management for local dev"},
            {"name": "middy", "reason": "middleware engine for AWS Lambda handlers"},
        ],
    },
    "devops_build": {
        "label": "DevOps / Build Tools",
        "keywords": [
            "build tool", "bundler", "webpack", "vite build", "esbuild",
            "toolchain", "build pipeline", "ci tooling", "linting setup",
            "code quality",
        ],
        "packages": [
            {"name": "vite", "reason": "fast modern build tool and dev server"},
            {"name": "esbuild", "reason": "extremely fast JavaScript bundler and minifier"},
            {"name": "typescript", "reason": "TypeScript compiler for type checking"},
            {"name": "eslint", "reason": "static code analysis and linting"},
            {"name": "prettier", "reason": "opinionated code formatter"},
            {"name": "husky", "reason": "Git hooks for pre-commit linting and checks"},
            {"name": "lint-staged", "reason": "run linters only on staged files"},
        ],
    },
    "testing": {
        "label": "Testing / QA",
        "keywords": [
            "testing", "qa", "test suite", "unit test", "e2e test",
            "end to end", "integration test", "jest", "cypress", "playwright",
        ],
        "packages": [
            {"name": "jest", "reason": "primary unit and integration test runner"},
            {"name": "cypress", "reason": "end-to-end browser testing with visual debugging"},
            {"name": "playwright", "reason": "cross-browser E2E testing with auto-wait"},
            {"name": "supertest", "reason": "HTTP assertion library for testing Express APIs"},
            {"name": "@testing-library/react", "reason": "component testing focused on user behaviour"},
            {"name": "nyc", "reason": "Istanbul-based code coverage reporting"},
        ],
    },
    "cli": {
        "label": "CLI Tools / Terminal Applications",
        "keywords": [
            "cli", "command line", "terminal tool", "node cli",
            "command-line", "interactive prompt", "terminal application",
        ],
        "packages": [
            {"name": "commander", "reason": "command argument parsing and subcommand routing"},
            {"name": "inquirer", "reason": "interactive prompts, selects, and confirmations"},
            {"name": "chalk", "reason": "terminal string styling and colours"},
            {"name": "ora", "reason": "elegant terminal spinner for async operations"},
            {"name": "boxen", "reason": "boxes and borders in terminal output"},
            {"name": "conf", "reason": "persistent configuration storage for CLI tools"},
        ],
    },
    "desktop": {
        "label": "Desktop Application Development",
        "keywords": [
            "desktop", "electron", "native app", "desktop app",
            "cross-platform app", "system tray", "menu bar app",
        ],
        "packages": [
            {"name": "electron", "reason": "framework for building cross-platform desktop apps with web tech"},
            {"name": "electron-builder", "reason": "packaging and auto-update for Electron apps"},
            {"name": "react", "reason": "UI layer for the Electron renderer process"},
            {"name": "react-dom", "reason": "DOM rendering for React in Electron"},
            {"name": "electron-store", "reason": "persistent local storage for app settings"},
        ],
    },
    "react_native": {
        "label": "Mobile Development (React Native)",
        "keywords": [
            "react native", "mobile", "ios", "android", "rn",
            "mobile app", "cross-platform mobile", "expo",
        ],
        "packages": [
            {"name": "react-native", "reason": "core React Native framework for mobile UI"},
            {"name": "typescript", "reason": "static typing for safer mobile code"},
            {"name": "@react-navigation/native", "reason": "navigation library for React Native screens"},
            {"name": "@react-native-async-storage/async-storage", "reason": "persistent local key-value storage"},
            {"name": "react-native-reanimated", "reason": "smooth, native-thread animations"},
            {"name": "detox", "reason": "end-to-end testing for React Native apps"},
        ],
    },
    "cms": {
        "label": "CMS / Content Management",
        "keywords": [
            "cms", "content management", "headless cms", "strapi",
            "ghost", "keystone", "admin panel", "content api",
        ],
        "packages": [
            {"name": "strapi", "reason": "open-source headless CMS with auto-generated REST and GraphQL APIs"},
            {"name": "@strapi/plugin-users-permissions", "reason": "user authentication and role management for Strapi"},
            {"name": "@strapi/plugin-i18n", "reason": "internationalisation and multi-locale content"},
            {"name": "sharp", "reason": "high-performance image processing for media uploads"},
        ],
    },
    "blockchain": {
        "label": "Blockchain / Web3 Development",
        "keywords": [
            "blockchain", "web3", "ethereum", "nft", "defi", "crypto",
            "smart contract", "dapp", "solidity", "hardhat", "truffle",
            "wallet", "token",
        ],
        "packages": [
            {"name": "ethers", "reason": "complete Ethereum library for interacting with contracts and wallets"},
            {"name": "hardhat", "reason": "Ethereum development environment for compiling and testing contracts"},
            {"name": "@walletconnect/client", "reason": "wallet connection protocol for dApps"},
            {"name": "web3", "reason": "alternative Ethereum JavaScript API"},
            {"name": "@openzeppelin/contracts", "reason": "audited smart contract libraries (ERC20, ERC721, etc.)"},
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
