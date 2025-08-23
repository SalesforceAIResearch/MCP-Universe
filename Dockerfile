WORKDIR /app

# Copy the entire project directory into the container.
# This assumes the Dockerfile is at the root of the project.
COPY . /app

# Install platform-specific requirements for Debian-based images.
# This is necessary for the `psycopg2` library which requires `libpq-dev`.
RUN apt-get update && apt-get install -y libpq-dev && rm -rf /var/lib/apt/lists/*

# Create and activate a Python virtual environment.
RUN python3 -m venv venv

# Install the dependencies from the requirements files.
# We explicitly use the venv's pip to ensure packages are installed correctly.
RUN /app/venv/bin/pip install -r requirements.txt
RUN /app/venv/bin/pip install -r dev-requirements.txt

# Install pre-commit hooks.
RUN /app/venv/bin/pre-commit install

# Copy the .env.example file to .env as per the instructions.
# This prepares the environment for configuration.
RUN cp .env.example .env

# Set the default command to start a bash shell, keeping the container running.
# The user can then interact with the environment and activate the venv manually.
CMD ["/bin/bash"]
