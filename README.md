# EazyDR - Doctor Appointment & Healthcare Management System

A modern, scalable FastAPI-based healthcare platform for managing doctor appointments, patient records, and medical services with JWT authentication, real-time features, and comprehensive role-based access control.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Authentication](#authentication)
- [Critical Issues & Bug Fixes](#critical-issues--bug-fixes)
- [Security Best Practices](#security-best-practices)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Support](#support)
- [License](#license)

## Features

### Core Functionality
- User registration and email verification
- Secure login with JWT authentication
- Doctor profiles with specialization and ratings
- Appointment booking, rescheduling, and cancellation
- Patient medical history and records
- Real-time appointment status updates
- Role-based access control (Patient, Doctor, Admin)

### Security & Performance
- JWT token-based authentication with refresh tokens
- Rate limiting on authentication endpoints (Redis-backed)
- Bcrypt password hashing
- Input validation using Pydantic
- CORS protection
- OTP-based password reset
- Email verification for new accounts

### Admin Features
- User account management
- Doctor verification and specialty management
- System analytics and reporting
- Account suspension and role management

## Tech Stack

**Backend**
- FastAPI 0.104.1 - Modern async web framework
- PostgreSQL 12+ - Relational database
- SQLAlchemy - ORM for database operations
- Pydantic - Data validation
- PyJWT - JWT authentication
- Bcrypt - Password hashing
- Redis - Caching and rate limiting
- Alembic - Database migrations

**DevOps**
- Docker & Docker Compose
- Uvicorn - ASGI server
- Celery - Task queue (async jobs)

## Quick Start

### Using Docker (Recommended)
```bash
git clone https://github.com/SudipMondalMAIN/EazyDR.git
cd EazyDR
cp .env.example .env
docker-compose up -d
```

API will be at `http://localhost:8000`  
Swagger Docs: `http://localhost:8000/docs`

### Manual Setup
```bash
git clone https://github.com/SudipMondalMAIN/EazyDR.git
cd EazyDR
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Installation

### Prerequisites
- Python 3.10 or higher
- PostgreSQL 12 or higher
- Redis 6.0 or higher
- Docker & Docker Compose (optional)

### Step-by-Step Setup

1. Clone the repository
```bash
git clone https://github.com/SudipMondalMAIN/EazyDR.git
cd EazyDR
```

2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Copy environment template
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Initialize database
```bash
alembic upgrade head
```

6. Start Redis
```bash
redis-server
```

7. Run application
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Configuration

Create `.env` file with these variables:

```env
# ===== DATABASE =====
DATABASE_URL=postgresql://user:password@localhost:5432/eazydr
DATABASE_ECHO=false
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# ===== JWT & SECURITY =====
SECRET_KEY=your-super-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# ===== EMAIL CONFIGURATION =====
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SENDER_EMAIL=noreply@eazydr.com

# ===== REDIS =====
REDIS_URL=redis://localhost:6379/0

# ===== CORS =====
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173

# ===== APPLICATION =====
APP_NAME=EazyDR
APP_VERSION=1.0.0
ENVIRONMENT=development
DEBUG=false
LOG_LEVEL=INFO

# ===== RATE LIMITING =====
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_PERIOD=3600

# ===== OTP SETTINGS =====
OTP_EXPIRY_MINUTES=10
OTP_LENGTH=6
```

## Project Structure

```
EazyDR/
├── app/
│   ├── main.py                    # FastAPI application entry point
│   ├── core/
│   │   ├── config.py             # Settings management
│   │   ├── database.py           # Database initialization
│   │   ├── security.py           # JWT & password utilities
│   │   ├── rate_limit.py         # Rate limiting logic
│   │   └── email.py              # Email sending service
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py         # Authentication routes
│   │   │   ├── service.py        # Auth business logic
│   │   │   ├── schemas.py        # Pydantic models
│   │   │   └── dependencies.py   # Dependency injection
│   │   ├── doctors/              # Doctor management
│   │   ├── appointments/         # Appointment handling
│   │   ├── patients/             # Patient profiles
│   │   └── admin/                # Admin functions
│   ├── models/                   # SQLAlchemy ORM models
│   ├── common/
│   │   ├── exceptions.py         # Custom exceptions
│   │   └── constants.py          # Application constants
│   └── middleware/               # Custom middleware
├── migrations/                   # Alembic database migrations
├── tests/                        # Unit & integration tests
├── docker-compose.yml            # Docker services
├── Dockerfile                    # Docker image
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
└── README.md
```

## API Documentation

### Interactive Docs (After Starting Server)
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Authentication Endpoints

**Register**
```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "first_name": "John",
  "last_name": "Doe",
  "role": "patient"
}
```

**Login**
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!"
}

Response:
{
  "access_token": "eyJ0eXAiOiJKV1Q...",
  "refresh_token": "eyJ0eXAiOiJKV1Q...",
  "user": { "id": "uuid", "email": "...", "role": "patient" }
}
```

**Request Password Reset**
```http
POST /api/v1/auth/forgot-password
Content-Type: application/json

{
  "email": "user@example.com"
}
```

### Doctor Endpoints

**List Doctors**
```http
GET /api/v1/doctors?specialty=cardiology&skip=0&limit=10

Response:
{
  "total": 45,
  "doctors": [
    {
      "id": "uuid",
      "name": "Dr. Smith",
      "specialty": "cardiology",
      "rating": 4.8,
      "available_slots": 15
    }
  ]
}
```

### Appointment Endpoints

**Book Appointment**
```http
POST /api/v1/appointments/book
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "doctor_id": "uuid",
  "appointment_date": "2024-02-15",
  "appointment_time": "10:00",
  "reason": "Consultation"
}
```

**Get My Appointments**
```http
GET /api/v1/appointments/my-appointments
Authorization: Bearer <access_token>
```

## Database Schema

### Users Table
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  first_name VARCHAR(100),
  last_name VARCHAR(100),
  role ENUM('patient', 'doctor', 'admin'),
  is_active BOOLEAN DEFAULT true,
  is_verified BOOLEAN DEFAULT false,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

### Doctors Table
```sql
CREATE TABLE doctors (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  specialty VARCHAR(100),
  license_number VARCHAR(100) UNIQUE,
  experience_years INTEGER,
  rating DECIMAL(3,2),
  is_verified BOOLEAN DEFAULT false,
  created_at TIMESTAMP
);
```

### Appointments Table
```sql
CREATE TABLE appointments (
  id UUID PRIMARY KEY,
  patient_id UUID REFERENCES users(id),
  doctor_id UUID REFERENCES doctors(id),
  appointment_date DATE,
  appointment_time TIME,
  status ENUM('pending', 'confirmed', 'completed', 'cancelled'),
  reason TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

## Authentication

Uses JWT (JSON Web Tokens) for secure, stateless authentication:

1. User creates account or logs in
2. Server returns `access_token` (short-lived) and `refresh_token` (long-lived)
3. Client sends token in Authorization header: `Authorization: Bearer <token>`
4. When access token expires, use refresh token to get new one

### Protected Routes
All endpoints except login/register/forgot-password require valid token.

## Critical Issues & Bug Fixes

### Critical Security Issues (Fix Before Production)

**1. Hardcoded JWT Secret**
- Location: `app/core/config.py`
- Issue: Default SECRET_KEY in code allows token forgery
- Fix: Generate strong secret, use environment variable only
```bash
# Generate new secret
openssl rand -base64 32
# Add to .env: SECRET_KEY=<generated_value>
```

**2. CORS Misconfiguration**
- Location: `app/main.py`
- Issue: Wildcard CORS with credentials enabled (CSRF vulnerability)
- Fix: Restrict to specific trusted domains
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specific domain only
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

**3. OTP Expiry Not Enforced**
- Location: `app/modules/auth/service.py`
- Issue: Password reset OTPs may persist indefinitely
- Fix: Add timestamp validation
```python
# Before verifying OTP, check:
if otp_record.created_at + timedelta(minutes=10) < datetime.now():
    raise OTPExpiredException()
```

**4. User Registration Race Condition**
- Issue: Multiple simultaneous registrations with same email
- Fix: Add database unique constraint and transaction handling

### High Priority Issues

**Missing Input Validation**
- Query parameters not validated (skip, limit)
- Can cause DoS or data exfiltration
- Add validation in schemas

**Error Messages Leak Details**
- Stack traces visible in responses
- Remove technical details in production

### Medium Priority Issues

- No pagination defaults on list endpoints
- No audit logging for sensitive operations
- Silent failures when Redis unavailable
- No database query timeouts

## Security Best Practices

### Before Production

1. **Change all secrets**
```bash
openssl rand -base64 32  # New JWT secret
```

2. **Fix CORS** - Whitelist specific domains only

3. **Enable HTTPS** - Use SSL certificates

4. **Database security**
   - Strong passwords
   - Enable SSL connections
   - Least privilege user
   - Regular backups

5. **Set environment properly**
```env
ENVIRONMENT=production
DEBUG=false
ALLOWED_ORIGINS=https://yourdomain.com
```

6. **Monitor & Log**
   - Log authentication attempts
   - Monitor suspicious activity
   - Set up alerts

7. **Dependencies**
   - Keep packages updated
   - Regular security audits
   - Use pip-audit to check vulnerabilities
```bash
pip install pip-audit
pip-audit
```

## Testing

```bash
# Run all tests
pytest tests/

# With coverage
pytest --cov=app tests/

# Specific test file
pytest tests/modules/auth/test_auth.py -v

# With output
pytest -v -s
```

## Deployment

### Docker Compose
```bash
docker-compose up -d
```

### Docker Manual
```bash
docker build -t eazydr:latest .
docker run -p 8000:8000 --env-file .env eazydr:latest
```

### Production Checklist
- [ ] Generate new SECRET_KEY
- [ ] Fix CORS configuration
- [ ] Enable HTTPS/SSL
- [ ] Set DEBUG=false
- [ ] Use production database
- [ ] Configure Redis for production
- [ ] Set up logging and monitoring
- [ ] Enable database backups
- [ ] Rate limit configured appropriately
- [ ] Run security audit

## Contributing

1. Fork repository
2. Create feature branch: `git checkout -b feature/AmazingFeature`
3. Commit changes: `git commit -m 'Add AmazingFeature'`
4. Push to branch: `git push origin feature/AmazingFeature`
5. Open Pull Request

### Code Standards
- Follow PEP 8
- Use type hints
- Write docstrings
- Run tests before PR
- Max line length: 100 chars

## Support

- GitHub Issues: [Report a bug](https://github.com/SudipMondalMAIN/EazyDR/issues)
- Discussions: GitHub Discussions tab
- Documentation: `/docs` endpoint after running server

## License

MIT License - See LICENSE file for details

## Authors

**Sudip Mondal** - [@SudipMondalMAIN](https://github.com/SudipMondalMAIN)

---

**Last Updated:** January 2024  
**Status:** Active Development  
**Version:** 1.0.0
