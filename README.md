# PO Review System

A comprehensive Purchase Order (PO) review and processing system with automated validation, pallet calculation, and document generation capabilities.

## 📋 Overview

The PO Review System is designed to streamline and automate the PO review process, featuring:

- **Automated PO Parsing**: Extract data from PDF purchase orders
- **Inventory Validation**: Check stock availability across multiple locations (MAIN/SUB)
- **Pallet Calculation**: Automatic pallet optimization for both MMD and EMD operations
- **Document Generation**: Generate Excel reports and shipping documents
- **Firebase Integration**: Real-time data synchronization and storage
- **User-Friendly Web Interface**: Modern web UI for easy operation

---

## 🚀 How to Run Locally

### Prerequisites

**1. Install Python (3.9 or higher)**

- **Windows**: Download from [python.org](https://www.python.org/downloads/)
  - ⚠️ **IMPORTANT**: Check "Add Python to PATH" during installation!
- **Mac**: 
  ```bash
  brew install python3
  ```
- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt update
  sudo apt install python3 python3-pip
  ```

**2. Obtain Firebase Credentials**

You need a Firebase service account key file to run this application:

- Contact your system administrator to get `serviceAccountKey.json`
- Place the file in the **project root directory** (same level as this README)

```
📂 prs (project root)
├── 📄 serviceAccountKey.json  ← Place here
├── 📄 README.md
├── 📄 requirements.txt
├── 📂 backend/
├── 📂 frontend/
└── ...
```

> ⚠️ **Security Note**: Never commit `serviceAccountKey.json` to version control. It's already included in `.gitignore`.

---

### Quick Start

Choose your operating system:

#### 🪟 **Windows**

1. **Double-click** `run_server_windows.bat`

   OR open Command Prompt/PowerShell in the project folder and run:
   ```cmd
   run_server_windows.bat
   ```

2. The script will automatically:
   - ✅ Check if Python is installed
   - ✅ Install all required dependencies
   - ✅ Start the FastAPI server

3. **Open your browser** and navigate to:
   - Main Application: **http://localhost:8001**
   - API Documentation: **http://localhost:8001/docs**

#### 🍎 **Mac / 🐧 Linux**

1. **First time only** - Make the script executable:
   ```bash
   chmod +x run_server_mac_linux.sh
   ```

2. **Run the script**:
   ```bash
   ./run_server_mac_linux.sh
   ```

3. The script will automatically:
   - ✅ Check if Python is installed
   - ✅ Install all required dependencies
   - ✅ Start the FastAPI server

4. **Open your browser** and navigate to:
   - Main Application: **http://localhost:8001**
   - API Documentation: **http://localhost:8001/docs**

---

### Manual Installation (Alternative Method)

If you prefer to run commands manually:

#### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

#### Step 2: Navigate to Backend Directory
```bash
cd backend
```

#### Step 3: Start the Server
```bash
python main.py
```

The server will start on **http://localhost:8001**

---

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the project root (optional):

```env
# Firebase Configuration
FIREBASE_CRED_PATH=serviceAccountKey.json

# Directory Paths (optional - defaults are provided)
TEMP_DIR=temp
OUTPUT_DIR=outputs
DATA_DIR=data
```

### Data Directory Structure

```
📂 prs/
├── 📂 data/           # Master data files (CSV, system config)
├── 📂 outputs/        # Generated reports and documents
├── 📂 temp/           # Temporary processing files
└── 📂 backend/        # Backend application code
```

---

## 📖 Usage Guide

### Main Features

#### 1. **MMD (Multi-Market Distribution)**
- Upload PO PDFs
- Validate against inventory
- Generate pallet configurations
- Export Excel reports

#### 2. **EMD (E-commerce Market Distribution)**
- Similar to MMD with e-commerce specific logic
- Custom pallet calculation rules

#### 3. **Admin Portal**
- Upload and manage master data (CSV files)
- Configure system settings
- View processing history

### API Endpoints

Access the interactive API documentation at:
- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc

---

## 🛠️ Development

### Project Structure

```
prs/
├── backend/
│   ├── main.py                    # FastAPI application entry point
│   ├── core/
│   │   └── config.py              # Configuration management
│   ├── routers/
│   │   ├── mmd.py                 # MMD API endpoints
│   │   ├── emd.py                 # EMD API endpoints
│   │   └── admin.py               # Admin API endpoints
│   └── services/
│       ├── data_loader.py         # CSV data loading
│       ├── po_parser.py           # PDF PO parsing
│       ├── validator.py           # Inventory validation
│       ├── palletizer.py          # Pallet calculation (MMD)
│       ├── palletizer_emd.py      # Pallet calculation (EMD)
│       ├── document_generator.py  # Excel/document generation
│       └── firebase_service.py    # Firebase integration
├── frontend/
│   ├── index.html                 # Landing page
│   ├── mmd.html                   # MMD interface
│   ├── emd.html                   # EMD interface
│   ├── admin.html                 # Admin interface
│   └── assets/                    # Static assets (CSS, JS, images)
├── data/                          # Master data files
├── outputs/                       # Generated output files
└── temp/                          # Temporary files
```

### Running in Development Mode

The server runs with **auto-reload** enabled by default, so code changes are automatically reflected.

```bash
cd backend
python main.py
```

Server logs will appear in the console showing:
- Request processing
- Data loading status
- Error messages

---

## 🐛 Troubleshooting

### Common Issues

**1. "Python is not recognized as a command"**
- Solution: Reinstall Python and ensure "Add to PATH" is checked
- Windows: Add Python to PATH manually via System Environment Variables

**2. "Firebase key file not found"**
- Solution: Ensure `serviceAccountKey.json` is in the project root
- Check that the filename is exactly `serviceAccountKey.json` (case-sensitive on Linux/Mac)

**3. "Port 8001 is already in use"**
- Solution: Stop any other application using port 8001
- Windows: `netstat -ano | findstr :8001` then `taskkill /PID <PID> /F`
- Linux/Mac: `lsof -ti:8001 | xargs kill -9`

**4. "Module not found" errors**
- Solution: Reinstall dependencies: `pip install -r requirements.txt`
- Try upgrading pip first: `pip install --upgrade pip`

**5. Permission denied (Mac/Linux)**
- Solution: Make the script executable: `chmod +x run_server_mac_linux.sh`

---

## 📦 Dependencies

Core dependencies (automatically installed by startup scripts):

- **FastAPI** (>=0.100.0) - Modern web framework
- **Uvicorn** (>=0.22.0) - ASGI server
- **Pandas** (>=2.0.0) - Data manipulation
- **PDFPlumber** (>=0.9.0) - PDF parsing
- **Firebase Admin** (>=6.2.0) - Firebase integration
- **OpenPyXL** (>=3.1.0) - Excel file handling
- **Python-multipart** (>=0.0.6) - File upload support
- **Python-dotenv** (>=1.0.0) - Environment variable management

---

## 🔒 Security

- Firebase credentials are **never** committed to the repository
- All sensitive files are excluded via `.gitignore`
- API endpoints include appropriate validation and error handling
- Output files are isolated in designated directories

---

## 📝 License

Internal use only - Proprietary software for company operations.

---

## 🤝 Support

For technical support or questions:
- Contact: Technical Lead
- Documentation: See `[필독] PO_Review_System_가이드.txt` for detailed Korean instructions

---

## 🎯 Version

**Current Version**: v3.5.0

---

**Happy Processing! 🚀**
