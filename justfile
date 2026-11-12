set shell := ["sh", "-cu"]

default:
    @just --list

# Install frontend dependencies
install:
    cd frontend && bun install

# Live preview of all components that have a components/**/*.preview.tsx file.
# Watches for added/removed previews and hot-reloads on every change.
# Open http://localhost:3000/preview
preview port="3000": install
    cd frontend && bun scripts/gen-previews.ts --watch & \
    pid=$!; trap 'kill $pid 2>/dev/null' EXIT INT TERM; \
    cd frontend && bun run dev -- --port {{port}}
