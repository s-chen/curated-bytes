# Local development only. Production is a static `npm run build` deployed to GitHub Pages.
FROM node:22-alpine

WORKDIR /app
RUN chown node:node /app
USER node

# Dependencies in their own layer, so editing code doesn't reinstall them.
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY --chown=node:node . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
