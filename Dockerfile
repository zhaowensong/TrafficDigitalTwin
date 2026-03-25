# 1. Use official lightweight Python 3.10 image to minimize build size
FROM python:3.10-slim

# 2. Define the working directory inside the container
WORKDIR /app

# 3. Create a non-root user with UID 1000 
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# 4. Copy requirements file and install dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the entire project source code and data assets to the container
COPY --chown=user . /app

# 6. Expose port 7860
EXPOSE 7860

# 7. Execute the Flask server script
CMD ["python", "server.py"]