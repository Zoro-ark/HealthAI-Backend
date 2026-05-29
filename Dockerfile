# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Install system dependencies (including Tesseract OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up user with UID 1000 (standard for Hugging Face Spaces)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy requirements file first
COPY --chown=user requirements-ml.txt $HOME/app/requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy all files into the container
COPY --chown=user . $HOME/app/

# Expose port 7860 (Hugging Face standard)
EXPOSE 7860

# Command to run uvicorn
CMD ["uvicorn", "ml_service.main:app", "--host", "0.0.0.0", "--port", "7860"]
