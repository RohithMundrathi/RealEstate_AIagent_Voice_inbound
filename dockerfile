# Use an official Python runtime as a parent image
FROM python:3.12.10-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True


# Copy local code to the container image.
ENV APP_HOME /apps
WORKDIR $APP_HOME
COPY . ./


# Install production dependencies.
RUN pip install -r requirements.txt
WORKDIR $APP_HOME/app


# Run the web service on container startup. Here we use the gunicorn
# web server, with 5 worker process and 30 threads.
# For environments with multiple CPU cores, increase the number of workers to be equal to the cores available.
# Timeout is set to 0 to disable the timeouts of the workers to allow Cloud Run to handle instance scaling.
CMD exec gunicorn --bind :$PORT --workers 4 main:app
