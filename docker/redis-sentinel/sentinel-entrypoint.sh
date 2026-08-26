#!/bin/sh
set -e

cat > /etc/sentinel.conf <<EOF
port 26379
sentinel announce-ip ${SENTINEL_NAME}
sentinel announce-port 26379
sentinel monitor mymaster redis-master 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 10000
sentinel parallel-syncs mymaster 1
EOF

exec redis-server /etc/sentinel.conf --sentinel
