import type { Metadata } from 'next'
import { LegalTitle, H2, P, A } from '../legal-content'

export const metadata: Metadata = { title: 'Imprint' }

export default function ImprintPage() {
  return (
    <>
      <LegalTitle updated="2026-07-07">Imprint</LegalTitle>

      <P>
        RoutePass is a personal, non-commercial software project. This instance at routepass.online is
        operated by an individual, not a registered business.
      </P>

      <H2>Responsible for this site</H2>
      <P>
        Joel Dettinger
        <br />
        Contact: <A href="mailto:dettinger.joel@gmail.com">dettinger.joel@gmail.com</A>
        <br />
        GitHub: <A href="https://github.com/dettinjo">github.com/dettinjo</A>
      </P>

      <H2>Disclaimer</H2>
      <P>
        This service is provided free of charge as a personal project and technology demonstration. See the{' '}
        <A href="/terms">Terms of Service</A> for the full disclaimer of warranty and liability. RoutePass is
        not affiliated with, endorsed by, or a representative of Strava, Komoot, Garmin, Intervals.icu,
        Runalyze, Google, or GitHub — all trademarks belong to their respective owners.
      </P>

      <H2>Data protection</H2>
      <P>
        See the <A href="/privacy">Privacy Policy</A> for details on data collection and processing.
      </P>
    </>
  )
}
