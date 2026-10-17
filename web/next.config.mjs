/** Static export: served from the Firebase Hosting CDN. /api/** is rewritten to Cloud Run. */
const nextConfig = {
  output: "export",
  reactStrictMode: true,
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;
