/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow running multiple firm instances at once without .next collisions
  distDir: process.env.NEXT_DIST_DIR || ".next",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "https://systemize-backend.onrender.com",
  },
};

module.exports = nextConfig;
