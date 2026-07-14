# Use a lightweight, stable Python image
FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install critical system dependencies for OpenCV, MediaPipe, OpenGL, and X11 rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    libglib2.0-0 \
    libgomp1 \
    libasound2 \
    # X11 & GUI libraries for cv2.imshow
    libsm6 \
    libxext6 \
    libxrender-dev \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Upgrade pip and install Python dependencies
# We pin numpy < 2.0 to avoid compatibility issues with older MediaPipe/OpenCV builds
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    opencv-python \
    mediapipe \
    "numpy<2"

# Copy the game script into the container
COPY fruit_ninja_opencv.py .

# Run the game when the container starts
CMD ["python", "fruit_ninja_opencv.py"]