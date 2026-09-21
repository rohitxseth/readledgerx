FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# --host binds to 0.0.0.0 so the dev server is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
