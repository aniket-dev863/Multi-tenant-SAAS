StreamPulse Pharma 💊☁️

A Cloud-Native, Multi-Tenant SaaS Pharmacy Management System

StreamPulse Pharma is an enterprise-grade Pharmacy Management System designed to modernize retail pharmacy operations. Built as a multi-tenant Software-as-a-Service (SaaS), it allows multiple independent pharmacies to manage inventory, process point-of-sale (POS) transactions, and track suppliers from a single centralized platform.

The system leverages a Polyglot Persistence Architecture (PostgreSQL + MongoDB) and offloads intensive reporting tasks to AWS Serverless Microservices (Lambda + S3) to ensure high availability, secure data isolation, and low-latency processing.

🚀 Key Features

Strict Multi-Tenant Isolation: Secure session-based routing and database constraints (pharmacy_id) mathematically guarantee that users only interact with data, inventory, and staff belonging to their registered pharmacy.

Serverless PDF Reporting: Offloads resource-heavy reporting tasks to a decoupled Node.js AWS Lambda microservice. The PDF is drawn in memory and delivered via secure, 5-minute cryptographic Amazon S3 Presigned URLs.

Predictive Inventory Analytics: Features an intelligent Burn-Rate Engine that uses an Exponential Moving Average (EMA) algorithm on historical transactions to predict stockout dates and trigger automated UI alerts.

Polyglot Database Strategy: Uses Amazon RDS (PostgreSQL) for strict relational data (financials, tenants, users) and MongoDB Atlas for flexible, schema-less document storage (medication metadata).

Point of Sale (POS): Fast checkout interface using server-side session arrays and PostgreSQL trigger functions to automatically deduct batch quantities upon checkout.

🛠️ Technology Stack

Backend Framework: Python 3.12, Flask, Gunicorn

Frontend: HTML5, CSS3, Bootstrap 5, Chart.js, Jinja2

Relational Database: PostgreSQL (Hosted on Amazon RDS)

NoSQL Database: MongoDB Atlas

Serverless Compute: AWS Lambda (Node.js 20.x, pdfkit)

Cloud Storage: Amazon S3

Automation: AWS EventBridge & APScheduler

Security: AWS IAM Roles (Principle of Least Privilege), Werkzeug Cryptography

🏗️ System Architecture

The Monolith (EC2): The core Flask application is hosted on an AWS EC2 instance (Ubuntu) running via Gunicorn as a background daemon.

Database Routing: * Transactions and Users -> Amazon RDS (PostgreSQL).

Medicine Descriptions and Logs -> MongoDB Atlas.

Decoupled Microservice: When a user requests a report, the EC2 instance securely invokes the Node.js Lambda function. The function generates the PDF, saves it to S3, and returns a secure download link.

💻 Local Development Setup

Prerequisites

Python 3.10+

Node.js (for testing the PDF microservice)

PostgreSQL installed locally (or an AWS RDS endpoint)

A MongoDB Atlas Cluster URI

1. Clone the Repository

git clone [https://github.com/aniket-dev863/Multi-tenant-SAAS.git](https://github.com/aniket-dev863/Multi-tenant-SAAS.git)
cd Multi-tenant-SAAS


2. Set Up the Python Virtual Environment

python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt


3. Environment Variables

Create a .env file in the root directory and add the following keys:

SECRET_KEY=your_secure_flask_secret_key

# PostgreSQL Connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pharmacy_db
DB_USER=postgres
DB_PASSWORD=your_password

# MongoDB Connection
MONGO_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority


4. Initialize the Database

# Run the schema file in your PostgreSQL instance
psql -U postgres -d pharmacy_db -f schema.sql


5. Run the Application

python app.py


The application will be available at http://localhost:5001.

☁️ AWS Deployment Guide

1. EC2 App Server (Ubuntu)

Provision an EC2 instance and SSH into the server.

Clone the repository and install dependencies via requirements.txt.

Start the Gunicorn daemon:

gunicorn --bind 0.0.0.0:5000 app:app --daemon


2. Serverless PDF Microservice (Lambda)

The Node.js code for the PDF generator is located in the pdf-worker/ directory.

Navigate to the folder: cd pdf-worker

Install dependencies: npm install

Zip the contents: zip -r pdf-worker.zip index.js node_modules package.json

Create an AWS Lambda function (Node.js runtime) named StreamPulse-PDF-Generator.

Upload the .zip file.

Important: Increase the Lambda timeout to 15 seconds.

3. Security (IAM Roles)

To ensure the EC2 instance can securely trigger the Lambda function without hardcoding AWS access keys:

Create an IAM Role with lambda:InvokeFunction permissions targeting your Lambda ARN.

Attach this IAM Role to your EC2 instance.

🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the issues page.

📝 License

This project is licensed under the MIT License.
