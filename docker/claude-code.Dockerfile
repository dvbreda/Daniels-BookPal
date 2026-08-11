# Claude Code in een container, om op de NAS aan BookPal te werken.
#
# Bewust een aparte container: dan hoef je niets op UGOS zelf te installeren en
# blijft alles opruimbaar met één `docker rm`.
FROM node:22-slim

# git en ripgrep gebruikt Claude Code zelf; de rest is nodig om BookPal in
# dezelfde container te kunnen draaien en testen.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        ripgrep \
        less \
        python3 \
        python3-venv \
        python3-pip \
        libarchive13 \
        libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

# De npm-installatie haalt hetzelfde binaire bestand op als het installatie-
# script; op een N100 (x86_64) is dat linux-x64.
RUN npm install -g @anthropic-ai/claude-code

# Alleen de docker-cliënt, niet de daemon: het volledige docker.io-pakket sleept
# een dockerd mee die we hier nooit draaien, en zijn postinst-scripts verwachten
# systemd. De statische tarball geeft alleen het binary; sha256 vastgezet zodat
# een build niet stilzwijgend een ander binary binnenhaalt op een socket die in
# de praktijk root op de NAS is (zie compose.claude.yml).
RUN curl -fsSL -o /tmp/docker-cli.tgz \
        https://download.docker.com/linux/static/stable/x86_64/docker-29.7.2.tgz && \
    echo "803d433f226db4776e1768fd319fc6c6e4935a456acf84fcc0080818b854bc8f  /tmp/docker-cli.tgz" | sha256sum -c - && \
    tar xzf /tmp/docker-cli.tgz -C /usr/local/bin --strip-components=1 docker/docker && \
    rm /tmp/docker-cli.tgz

# De compose-plugin zit niet in de statische docker-tarball hierboven, en
# `docker compose up` is hoe compose.yml zelf draait. Systeembreed pad, zodat
# het los staat van welke user de container draait.
RUN mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
        https://github.com/docker/compose/releases/download/v5.4.0/docker-compose-linux-x86_64 && \
    echo "837fd1d35bf6a494f41b5b5988269a7be79de337cf1a1a6ff0e45ab51bb4e9be  /usr/local/lib/docker/cli-plugins/docker-compose" | sha256sum -c - && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Niet als root werken. UID 1000 komt meestal overeen met de eerste UGOS-
# gebruiker, zodat bestanden die Claude aanmaakt van jou blijven.
ARG UID=1000
ARG GID=1000
# GID van /var/run/docker.sock op de host — anders kan `node` de gemounte
# socket niet gebruiken. Opvragen met: stat -c '%g' /var/run/docker.sock
ARG DOCKER_GID=999
RUN groupmod -g ${GID} node 2>/dev/null || true; \
    usermod -u ${UID} -g ${GID} node 2>/dev/null || true; \
    (getent group ${DOCKER_GID} || groupadd -g ${DOCKER_GID} dockerhost) && \
    usermod -aG ${DOCKER_GID} node; \
    mkdir -p /home/node/.claude /workspace && chown -R ${UID}:${GID} /home/node /workspace
USER node

ENV HOME=/home/node
WORKDIR /workspace

# Blijft draaien zodat je er met `docker exec -it` in kunt.
CMD ["sleep", "infinity"]
