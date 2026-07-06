import { defineConfig } from 'astro/config'
import starlight from '@astrojs/starlight'

export default defineConfig({
  integrations: [
    starlight({
      title: 'RoutePass Docs',
      description: 'Middleware for fitness activity data — connect sources, destinations, and sync rules.',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/dettinjo/routepass' },
      ],
      editLink: {
        baseUrl: 'https://github.com/dettinjo/routepass/edit/main/docs/',
      },
      sidebar: [
        {
          label: 'Getting Started',
          items: [
            { label: 'Quickstart', link: '/getting-started/quickstart/' },
            { label: 'Data Handling', link: '/getting-started/data-handling/' },
            { label: 'Self-Hosting', link: '/getting-started/self-hosting/' },
          ],
        },
        {
          label: 'Connections',
          items: [
            { label: 'Overview', link: '/connections/overview/' },
            { label: 'Komoot', link: '/connections/komoot/' },
            { label: 'Strava', link: '/connections/strava/' },
            { label: 'Intervals.icu', link: '/connections/intervals-icu/' },
            { label: 'Runalyze', link: '/connections/runalyze/' },
          ],
        },
        {
          label: 'Sync Rules',
          items: [
            { label: 'Overview', link: '/sync-rules/overview/' },
            { label: 'Conditions', link: '/sync-rules/conditions/' },
            { label: 'Actions', link: '/sync-rules/actions/' },
          ],
        },
        {
          label: 'API',
          items: [
            { label: 'Authentication', link: '/api/authentication/' },
            { label: 'Reference', link: '/api/reference/' },
            { label: 'Rate Limits', link: '/api/rate-limits/' },
          ],
        },
        { label: 'Webhooks', link: '/webhooks/' },
      ],
      customCss: ['./src/styles/custom.css'],
    }),
  ],
})
