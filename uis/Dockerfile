FROM node:20-alpine

WORKDIR /app/uis/website

# Build context is the monorepo root so shared source imports (@repo/*)
# are available both during image builds and when running the container.
COPY uis/website/package.json uis/website/package-lock.json ./
RUN npm ci

COPY uis/website/ .
COPY src/ /app/src/
COPY uis/start.sh /app/uis/start.sh
RUN chmod +x /app/uis/start.sh

# Expose the port Next.js runs on by default
EXPOSE 3000

CMD ["/app/uis/start.sh"]