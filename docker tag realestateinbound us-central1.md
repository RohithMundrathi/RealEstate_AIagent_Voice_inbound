docker tag realestateinbound us-central1-docker.pkg.dev/real-estate-agent-458509/ai-agent-inbound/realestateinbound

docker tag gcr.io/real-estate-agent-458509/ai-agent-inbound/realestateinbound

gcloud artifacts repositories describe ai-agent-inbound --project=real-estate-agent-458509 --location=us-central1