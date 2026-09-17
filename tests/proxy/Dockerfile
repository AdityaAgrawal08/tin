FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends squid-openssl nftables curl openssl iproute2 python3 ca-certificates dnsmasq-base && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
