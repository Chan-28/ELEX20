FROM tensorflow/tensorflow:2.18.0

WORKDIR /app

RUN pip install --no-cache-dir "kagglehub>=0.3" "numpy>=1.26"

COPY train.py /app/train.py

ENTRYPOINT ["python3", "-u", "train.py"]
