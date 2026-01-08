# Niyam AI 🤖

**AI-Powered Compliance & Regulatory Intelligence Platform**

![Niyam AI Banner](https://img.shields.io/badge/Niyam-AI-blueviolet)
![Version](https://img.shields.io/badge/Version-MVP-orange)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

## 📋 Overview
Niyam AI is an intelligent compliance assistant that helps organizations navigate complex regulatory landscapes using artificial intelligence. Our platform automates regulatory tracking, compliance monitoring, and policy management.

**Live Demo:** [Coming Soon] | **Documentation:** [Coming Soon]

## ✨ Key Features

### 🚀 MVP Features (Currently Available)
- **AI Regulatory Scanner** - Automated detection of relevant regulations
- **Compliance Dashboard** - Real-time compliance status tracking
- **Document Intelligence** - Smart analysis of compliance documents
- **Alert System** - Proactive notifications for regulatory changes
- **Report Generator** - Automated compliance reporting

### 🔮 Upcoming Features
- Multi-jurisdictional compliance mapping
- AI-powered risk assessment
- Integration with existing GRC systems
- Automated audit trail generation
- Regulatory change impact analysis

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│                   Niyam AI                       │
├─────────────────────────────────────────────────┤
│  Frontend (React/Vue.js)     │  Mobile (React   │
│  • Compliance Dashboard      │  Native/Flutter) │
│  • Analytics Interface       │  • On-the-go     │
│  • Report Viewer             │    compliance    │
├─────────────────────────────────────────────────┤
│               API Layer (FastAPI/Node.js)       │
│  • Authentication Service    │  • Data          │
│  • Document Processing       │    Encryption    │
├─────────────────────────────────────────────────┤
│          AI/ML Engine (Python)                  │
│  • NLP for Regulation        │  • Predictive    │
│    Analysis                  │    Analytics     │
│  • OCR for Document          │  • Anomaly       │
│    Processing                │    Detection     │
├─────────────────────────────────────────────────┤
│           Data Layer                            │
│  • PostgreSQL (Structured)   │  • Redis (Cache) │
│  • Elasticsearch (Documents) │  • S3/Files      │
└─────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites
```bash
# Python 3.8+
python --version

# Node.js 16+ (for frontend)
node --version

# PostgreSQL 12+
# Redis (optional, for caching)
```

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/Ram-82/Niyam-AI.git
cd Niyam-AI
```

2. **Set up Python environment**
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Initialize database**
```bash
python manage.py migrate
python manage.py createsuperuser
```

5. **Run the application**
```bash
# Development server
python manage.py runserver

# Or with Docker
docker-compose up --build
```

## 📁 Project Structure

```
Niyam-AI/
├── backend/                 # Django/FastAPI backend
│   ├── api/                # API endpoints
│   ├── core/               # Core functionality
│   ├── ml_engine/          # AI/ML models
│   └── utils/              # Utilities
├── frontend/               # React/Vue frontend
│   ├── src/
│   │   ├── components/     # UI components
│   │   ├── pages/         # Page components
│   │   └── services/      # API services
├── mobile/                 # Mobile application
├── docs/                   # Documentation
├── tests/                  # Test suites
└── docker/                 # Docker configurations
```

## 🧪 Testing

```bash
# Run all tests
python -m pytest

# Run with coverage
pytest --cov=backend tests/

# Frontend tests
cd frontend && npm test
```

## 🔧 Configuration

### Environment Variables
```env
# Database
DATABASE_URL=postgresql://user:password@localhost/niyam_ai

# AI Services
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# Security
SECRET_KEY=your_secret_key
JWT_SECRET=your_jwt_secret

# External Services
SLACK_WEBHOOK_URL=your_webhook
EMAIL_HOST=smtp.gmail.com
```

### API Endpoints (Key)
| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/api/v1/regulations` | GET | List regulations | Yes |
| `/api/v1/scan` | POST | Scan document | Yes |
| `/api/v1/compliance` | GET | Compliance status | Yes |
| `/api/v1/alerts` | GET | Get alerts | Yes |
| `/api/v1/reports` | POST | Generate report | Yes |

## 📊 Data Flow

```mermaid
graph LR
    A[Regulatory Sources] --> B[Data Ingestion]
    B --> C[AI Processing]
    C --> D[Compliance Rules]
    D --> E[User Dashboard]
    E --> F[Actions & Alerts]
    F --> G[Audit Trail]
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md).

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Guidelines
```bash
# Install pre-commit hooks
pre-commit install

# Run linter
flake8 backend/

# Run formatter
black backend/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Contact & Support

**Founder:** Ramachandragowda S Patil
- **Email:** ramachandragowdasp19@gmail.com
- **LinkedIn:** https://www.linkedin.com/in/ramachandragowda-s-p-avgx
- **Website:** [Coming Soon]

**Support Channels:**
- GitHub Issues: [Report Bugs](https://github.com/Ram-82/Niyam-AI/issues)
- Documentation: [Coming Soon]
- Email Support: support@niyam.ai

## 🚀 Deployment

### Cloud Deployment (AWS Example)
```bash
# Deploy to AWS Elastic Beanstalk
eb init -p python-3.8 niyam-ai
eb create niyam-ai-prod

# Or using Docker
docker build -t niyam-ai .
docker push your-registry/niyam-ai
```

### Environment Setup
```yaml
# docker-compose.yml example
version: '3.8'
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgres://...
  db:
    image: postgres:13
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

## 🌟 Acknowledgments

- Regulatory data sources and APIs
- Open-source AI/ML libraries
- Our early beta testers and contributors
- The compliance and legal tech community

---

<div align="center">
  
**Built with ❤️ for simplifying compliance**

[![GitHub stars](https://img.shields.io/github/stars/Ram-82/Niyam-AI?style=social)](https://github.com/Ram-82/Niyam-AI/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Ram-82/Niyam-AI?style=social)](https://github.com/Ram-82/Niyam-AI/network/members)

*Star this repo if you find it useful!*
</div>

---

**📌 Note:** This is an MVP version. Features and architecture are subject to change as we gather user feedback and evolve the product.

---

**Quick Links:** [Demo](#) | [Documentation](#) | [API Reference](#) | [Roadmap](ROADMAP.md) | [Changelog](CHANGELOG.md)

---

*© 2026 Niyam AI. All rights reserved. "Niyam" means "Rules" in Sanskrit, reflecting our mission to simplify complex regulations.*
