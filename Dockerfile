# This is the Dockerfile for ArchiveBox, it bundles the following dependencies:
#     python3, ArchiveBox, curl, wget, git, chromium, youtube-dl, single-file
# Usage:
#     docker build . -t archivebox --no-cache
#     docker run -v "$PWD/data":/data archivebox init
#     docker run -v "$PWD/data":/data archivebox add 'https://example.com'
#     docker run -v "$PWD/data":/data -it archivebox manage createsuperuser
#     docker run -v "$PWD/data":/data -p 8000:8000 archivebox server

FROM python:3.9-slim-buster

LABEL name="archivebox" \
    maintainer="Nick Sweeting <archivebox-docker@sweeting.me>" \
    description="All-in-one personal internet archiving container" \
    homepage="https://github.com/ArchiveBox/ArchiveBox" \
    documentation="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker"

# System-level base config
ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1

# Application-level base config
ENV CODE_DIR=/app \
    VENV_PATH=/venv \
    DATA_DIR=/data \
    NODE_DIR=/node \
    ARCHIVEBOX_USER="archivebox"

# Create non-privileged user for archivebox and chrome
RUN groupadd --system $ARCHIVEBOX_USER \
    && useradd --system --create-home --gid $ARCHIVEBOX_USER --groups audio,video $ARCHIVEBOX_USER

# Install system dependencies
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        apt-transport-https ca-certificates gnupg2 zlib1g-dev \
        dumb-init gosu cron unzip curl \
    && rm -rf /var/lib/apt/lists/*

# Install apt dependencies
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        wget curl chromium git ffmpeg youtube-dl ripgrep \
        fontconfig fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst fonts-symbola fonts-noto fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install Node environment
RUN curl -s https://deb.nodesource.com/gpgkey/nodesource.gpg.key | apt-key add - \
    && echo 'deb https://deb.nodesource.com/node_15.x buster main' >> /etc/apt/sources.list \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        nodejs \
    # && npm install -g npm \
    && rm -rf /var/lib/apt/lists/*

# Install Node dependencies
WORKDIR "$NODE_DIR"
ENV PATH="${PATH}:$NODE_DIR/node_modules/.bin" \
    npm_config_loglevel=error
ADD ./package.json ./package.json
ADD ./package-lock.json ./package-lock.json
RUN npm ci

# Install Python dependencies
WORKDIR "$CODE_DIR"
ENV PATH="${PATH}:$VENV_PATH/bin"
RUN python -m venv --clear --symlinks "$VENV_PATH" \
    && pip install --upgrade --quiet pip setuptools \
    && mkdir -p "$CODE_DIR/archivebox"
ADD "./setup.py" "$CODE_DIR/"
ADD "./package.json" "$CODE_DIR/archivebox/"
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        build-essential python-dev python3-dev \
    && echo 'empty placeholder for setup.py to use' > "$CODE_DIR/archivebox/README.md" \
    && python3 -c 'from distutils.core import run_setup; result = run_setup("./setup.py", stop_after="init"); print("\n".join(result.install_requires + result.extras_require["sonic"]))' > /tmp/requirements.txt \
    && pip install --quiet -r /tmp/requirements.txt \
    && apt-get purge -y build-essential python-dev python3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install apt development dependencies
# RUN apt-get install -qq \
#     && apt-get install -qq -y --no-install-recommends \
#         python3 python3-dev python3-pip python3-venv python3-all \
#         dh-python debhelper devscripts dput software-properties-common \
#         python3-distutils python3-setuptools python3-wheel python3-stdeb
# RUN python3 -c 'from distutils.core import run_setup; result = run_setup("./setup.py", stop_after="init"); print("\n".join(result.extras_require["dev"]))' > /tmp/dev_requirements.txt \
    # && pip install --quiet -r /tmp/dev_requirements.txt

# Install ArchiveBox Python package and its dependencies
WORKDIR "$CODE_DIR"
ADD . "$CODE_DIR"
RUN pip install -e .

# Setup ArchiveBox runtime config
WORKDIR "$DATA_DIR"
ENV IN_DOCKER=True \
    CHROME_SANDBOX=False \
    CHROME_BINARY="chromium" \
    USE_SINGLEFILE=True \
    SINGLEFILE_BINARY="$NODE_DIR/node_modules/.bin/single-file" \
    USE_READABILITY=True \
    READABILITY_BINARY="$NODE_DIR/node_modules/.bin/readability-extractor" \
    USE_MERCURY=True \
    MERCURY_BINARY="$NODE_DIR/node_modules/.bin/mercury-parser"

# Print version for nice docker finish summary
# RUN archivebox version
RUN /app/bin/docker_entrypoint.sh archivebox version

# Open up the interfaces to the outside world
VOLUME "$DATA_DIR"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=20s --retries=15 \
    CMD curl --silent 'http://localhost:8000/admin/login/' || exit 1

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh"]
CMD ["archivebox", "server", "--quick-init", "0.0.0.0:8000"]
