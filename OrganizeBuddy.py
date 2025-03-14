import os
import shutil
import re
import hashlib
import logging
import json
from collections import defaultdict, deque
from pathlib import Path
import nltk
from nltk.corpus import stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
from tqdm import tqdm

# Download necessary NLTK data
nltk.download('stopwords')
nltk.download('punkt')

# Configuration
SOURCE_DIR = r"D:\OneDrive\! visual studio\powershell"  # Change this to your actual directory
TARGET_DIR = os.path.join(SOURCE_DIR, "organized_library")
LOGS_TEMP_DIR = os.path.join(SOURCE_DIR, "logs_and_temp")
UNDO_LOG_FILE = os.path.join(LOGS_TEMP_DIR, "file_movement_log.json")

# Ensure necessary directories exist
os.makedirs(TARGET_DIR, exist_ok=True)
os.makedirs(LOGS_TEMP_DIR, exist_ok=True)

# Logging configuration
LOG_FILE = os.path.join(LOGS_TEMP_DIR, "file_reorganization.log")
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Windows Reserved Filenames
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                          "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}

# User selection
print("\nChoose an operation:")
print("[1] Perform a full reorganization (rename & move files)")
print("[2] Dry-run (show changes without renaming/moving)")
print("[3] Rollback last reorganization (restore files)")
choice = input("Enter choice (1, 2, or 3): ").strip()

if choice == "3" and os.path.exists(UNDO_LOG_FILE):
    with open(UNDO_LOG_FILE, "r") as f:
        file_movements = json.load(f)
    for new_path, original_path in file_movements.items():
        if os.path.exists(new_path):
            shutil.move(new_path, original_path)
            logging.info(f"Rolled back: {new_path} -> {original_path}")
    os.remove(UNDO_LOG_FILE)
    print("\nRollback complete! Files restored to their original locations.")
    exit()
elif choice == "3":
    print("\nNo rollback data found. Nothing to restore.")
    exit()

dry_run = choice == "2"
print("\nDry-run mode enabled: NO files will be renamed or moved." if dry_run else "\nExecuting full reorganization...")

# Detect script type based on content
def detect_script_type(content):
    patterns = {
        "py": [r"^import\s", r"^from\s", r"def\s", r"class\s"],
        "sh": [r"^#!.*\bsh\b", r"\bfunction\b", r"\becho\b"],
        "ps1": [r"^#!.*powershell", r"Write-Host", r"Get-Process", r"\$[a-zA-Z_]"],
        "bat": [r"@echo off", r"SET ", r"CALL ", r"EXIT /B"],
        "cmd": [r"cmd.exe", r"echo ", r"set ", r"exit "],
        "js": [r"function\s", r"var\s", r"const\s", r"let\s"],
        "html": [r"<html>", r"<head>", r"<body>"],
    }
    for ext, regex_list in patterns.items():
        for regex in regex_list:
            if re.search(regex, content, re.MULTILINE | re.IGNORECASE):
                return ext
    return None

# Extract keywords for categorization
def extract_keywords(text, top_n=5):
    stop_words = set(stopwords.words('english'))
    words = nltk.word_tokenize(text)
    words = [w.lower() for w in words if w.isalnum() and w not in stop_words]
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform([" ".join(words)])
    feature_array = vectorizer.get_feature_names_out()
    tfidf_scores = tfidf_matrix.toarray()[0]
    keywords = sorted(zip(feature_array, tfidf_scores), key=lambda x: x[1], reverse=True)[:top_n]
    return [kw[0] for kw in keywords]

# Generate a hash for duplicate files
def hash_content(content):
    return hashlib.md5(content.encode()).hexdigest()[:8]

# Gather all files
all_files = []
for root, _, files in os.walk(SOURCE_DIR):
    if LOGS_TEMP_DIR in root or TARGET_DIR in root:
        continue
    for file in files:
        all_files.append(Path(root) / file)

# Progress bar
progress_bar = tqdm(total=len(all_files), desc="Processing Files", dynamic_ncols=True)
rolling_list = deque(maxlen=5)
categorized_files = defaultdict(list)
file_movements = {}

# Process files
for file_path in all_files:
    original_ext = file_path.suffix.lower()
    # Handle non-text files
    if original_ext in [".zip", ".exe", ".pdf", ".jpg", ".png", ".mp4"]:
        new_path = Path(TARGET_DIR) / "non_text_files" / file_path.name
        os.makedirs(new_path.parent, exist_ok=True)
        if not dry_run:
            shutil.move(file_path, new_path)
            file_movements[str(new_path)] = str(file_path)
        logging.info(f"Moved non-text file: {file_path} -> {new_path}")
        progress_bar.update(1)
        continue

    # Process text-based files
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # Detect misnamed scripts
            new_ext = detect_script_type(content)
            if new_ext and original_ext == ".txt":
                new_file_path = file_path.with_suffix(f".{new_ext}")
                if not dry_run:
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                logging.info(f"Renamed: {file_path.name} to {new_file_path.name}")
            # Categorization
            keywords = extract_keywords(content)
            category = "_".join(keywords) if keywords else "miscellaneous"
            category = "".join(c if c.isalnum() or c in "_-" else "_" for c in category)
            if category.upper() in WINDOWS_RESERVED_NAMES:
                category += "_file"
            # Generate new name
            new_name = f"{category}_{hash_content(content)}{file_path.suffix}"
            categorized_files[category].append((file_path, new_name))
            rolling_list.append(file_path.name)
            progress_bar.set_postfix({"Last 5": list(rolling_list)})
            progress_bar.update(1)
    except Exception as e:
        logging.error(f"Error processing {file_path}: {e}")
        progress_bar.update(1)

# Move files
for category, files in categorized_files.items():
    category_path = Path(TARGET_DIR) / category
    category_path.mkdir(parents=True, exist_ok=True)
    for old_path, new_name in files:
        new_path = category_path / new_name
        if not dry_run:
            shutil.move(old_path, new_path)
            file_movements[str(new_path)] = str(old_path)
        logging.info(f"Moved {old_path} -> {new_path}")

# Save undo log
if not dry_run:
    with open(UNDO_LOG_FILE, "w") as f:
        json.dump(file_movements, f, indent=4)

progress_bar.close()
print("\nReorganization complete! Log file saved in logs_and_temp.")

# Additional Features

# Feature: Generate a summary report of the reorganization
def generate_report():
    report_file = os.path.join(LOGS_TEMP_DIR, "reorganization_summary.txt")
    with open(report_file, 'w') as f:
        f.write("Reorganization Summary:\n")
        f.write("=======================\n\n")
        for category, files in categorized_files.items():
            f.write(f"Category: {category}\n")
            f.write("-" * 30 + "\n")
            for old_path, new_name in files:
                f.write(f"{old_path} -> {new_path}\n")
            f.write("\n")

if not dry_run:
    generate_report()
    logging.info("Summary report generated.")
    print("A summary report has been generated and saved to logs_and_temp.")

# Feature: Add an option to clean up empty directories
def cleanup_empty_directories():
    for root, dirs, _ in os.walk(SOURCE_DIR):
        if not dirs and not [f for f in os.listdir(root) if not f.startswith('.')]:
            try:
                os.rmdir(root)
                logging.info(f"Removed empty directory: {root}")
            except Exception as e:
                logging.error(f"Error removing directory {root}: {e}")

if not dry_run:
    cleanup_empty_directories()
    print("Empty directories have been cleaned up.")

# Feature: Allow user to specify which file types to include/exclude
def get_file_types_to_include():
    while True:
        file_types = input("Enter comma-separated file extensions to include (e.g., .txt,.py) or press Enter for default: ").strip()
        if not file_types:
            return None  # Return None to use default behavior
        try:
            file_extensions = set(ext.strip().lower() for ext in file_types.split(","))
            if all(ext.startswith('.') for ext in file_extensions):
                return file_extensions
            else:
                print("Please ensure all extensions start with a dot (e.g., .txt, .py).")
        except Exception as e:
            logging.error(f"Error parsing file types: {e}")
            print("Invalid input. Please try again.")

file_types_to_include = get_file_types_to_include()
if file_types_to_include is not None:
    all_files = [f for f in all_files if f.suffix.lower() in file_types_to_include]

# Re-run the reorganization process with user-specified file types
categorized_files = defaultdict(list)
file_movements = {}
for file_path in all_files:
    original_ext = file_path.suffix.lower()
    # Handle non-text files
    if original_ext in [".zip", ".exe", ".pdf", ".jpg", ".png", ".mp4"]:
        new_path = Path(TARGET_DIR) / "non_text_files" / file_path.name
        os.makedirs(new_path.parent, exist_ok=True)
        if not dry_run:
            shutil.move(file_path, new_path)
            file_movements[str(new_path)] = str(file_path)
        logging.info(f"Moved non-text file: {file_path} -> {new_path}")
        progress_bar.update(1)
        continue

    # Process text-based files
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # Detect misnamed scripts
            new_ext = detect_script_type(content)
            if new_ext and original_ext == ".txt":
                new_file_path = file_path.with_suffix(f".{new_ext}")
                if not dry_run:
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                logging.info(f"Renamed: {file_path.name} to {new_file_path.name}")
            # Categorization
            keywords = extract_keywords(content)
            category = "_".join(keywords) if keywords else "miscellaneous"
            category = "".join(c if c.isalnum() or c in "_-" else "_" for c in category)
            if category.upper() in WINDOWS_RESERVED_NAMES:
                category += "_file"
            # Generate new name
            new_name = f"{category}_{hash_content(content)}{file_path.suffix}"
            categorized_files[category].append((file_path, new_name))
            rolling_list.append(file_path.name)
            progress_bar.set_postfix({"Last 5": list(rolling_list)})
            progress_bar.update(1)
    except Exception as e:
        logging.error(f"Error processing {file_path}: {e}")
        progress_bar.update(1)

# Move files
for category, files in categorized_files.items():
    category_path = Path(TARGET_DIR) / category
    category_path.mkdir(parents=True, exist_ok=True)
    for old_path, new_name in files:
        new_path = category_path / new_name
        if not dry_run:
            shutil.move(old_path, new_path)
            file_movements[str(new_path)] = str(old_path)
        logging.info(f"Moved {old_path} -> {new_path}")

# Save undo log
if not dry_run:
    with open(UNDO_LOG_FILE, "w") as f:
        json.dump(file_movements, f, indent=4)

progress_bar.close()
print("\nReorganization complete! Log file saved in logs_and_temp.")