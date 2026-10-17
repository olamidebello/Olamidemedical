FROM python:3.12-slim
RUN useradd --create-home --uid 10001 hospital
WORKDIR /app
COPY --chown=hospital:hospital server.py ./
COPY --chown=hospital:hospital static ./static
RUN mkdir /app/data && chown hospital:hospital /app/data
USER hospital
EXPOSE 8080
CMD ["python", "server.py", "--host", "0.0.0.0"]
