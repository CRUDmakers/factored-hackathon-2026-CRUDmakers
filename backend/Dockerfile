# ---- build: instala tudo, gera o Prisma Client e compila (também usado para rodar os testes)
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY prisma ./prisma
COPY prisma.config.ts tsconfig.json tsconfig.build.json vitest.config.ts ./
COPY src ./src
COPY tests ./tests
RUN npm run build

# ---- runtime: só dependências de produção e o JS compilado
FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY prisma ./prisma
COPY prisma.config.ts ./
COPY --from=build /app/dist ./dist
USER node
EXPOSE 3000
# Aplica as migrações pendentes e sobe a API.
CMD ["sh", "-c", "npx prisma migrate deploy && node dist/main.js"]
