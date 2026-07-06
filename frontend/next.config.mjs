/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async rewrites() {
    // INTERNAL_API_URL: server-side only build-time var (no NEXT_PUBLIC_ prefix).
    // Local dev (.env.local):  INTERNAL_API_URL=http://localhost:8000
    // Docker    (build arg):   INTERNAL_API_URL=http://api:8000
    //
    // Source  /api/:path*  captures everything after /api/ (e.g. "v1/health")
    // Dest    ${apiBase}/api/:path*  → http://api:8000/api/v1/health  ✓
    const apiBase  = process.env.INTERNAL_API_URL  || 'http://localhost:8000'
    const docsBase = process.env.INTERNAL_DOCS_URL || 'http://localhost:4321'
    return [
      {
        source:      '/api/:path*',
        destination: `${apiBase}/api/:path*`,
      },
      {
        source:      '/docs',
        destination: `${docsBase}/`,
      },
      {
        source:      '/docs/:path*',
        destination: `${docsBase}/:path*`,
      },
      // Astro/Starlight serves its compiled assets at /_astro/* — proxy them so
      // the docs page loads CSS/JS when accessed via the Next.js rewrite.
      {
        source:      '/_astro/:path*',
        destination: `${docsBase}/_astro/:path*`,
      },
    ]
  },
}

export default nextConfig
