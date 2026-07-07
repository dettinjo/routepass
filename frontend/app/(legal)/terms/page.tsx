import type { Metadata } from 'next'
import { LegalTitle, H2, P, Ul, A } from '../legal-content'

export const metadata: Metadata = { title: 'Terms of Service' }

export default function TermsPage() {
  return (
    <>
      <LegalTitle updated="2026-07-07">Terms of Service</LegalTitle>

      <P>
        These terms govern your use of the RoutePass instance hosted at routepass.online. By creating an
        account, you agree to the terms below.
      </P>

      <H2>The service</H2>
      <P>
        RoutePass lets you connect fitness platforms (Strava, Komoot, Garmin Connect, Intervals.icu, Runalyze)
        and configure pipelines that automatically route activities between them, optionally filtered or
        transformed by sync rules you define. This instance runs in self-hosted mode: it is provided free of
        charge, without payment processing or paid tiers.
      </P>

      <H2>Your responsibilities</H2>
      <Ul>
        <li>Only connect accounts you own or are authorized to use.</li>
        <li>Don&apos;t use the service to violate the terms of connected third-party platforms (Strava, Komoot, etc.).</li>
        <li>Don&apos;t attempt to circumvent rate limits, abuse the API, or interfere with the service&apos;s availability for other users.</li>
        <li>Keep your login credentials confidential.</li>
      </Ul>

      <H2>Third-party platforms</H2>
      <P>
        RoutePass is not affiliated with Strava, Komoot, Garmin, Intervals.icu, Runalyze, Google, or GitHub.
        Each platform&apos;s own terms of service apply to your account there. Strava&apos;s API access, for instance,
        is subject to Strava&apos;s own developer program terms and rate limits, which are outside our control and
        may change at any time.
      </P>

      <H2>Availability & no warranty</H2>
      <P>
        This is a personal, non-commercial demo instance. It is provided <strong>as-is</strong>, without
        warranty of any kind, and without any uptime or data-durability guarantee. Sync operations depend on
        third-party APIs that may rate-limit, deprecate endpoints, or become temporarily unavailable outside
        our control. Back up anything you cannot afford to lose.
      </P>

      <H2>Limitation of liability</H2>
      <P>
        To the maximum extent permitted by law, the operator is not liable for any indirect, incidental, or
        consequential damages arising from use of the service, including data loss, missed syncs, or
        third-party platform actions (e.g. rate limiting or account suspension) resulting from API usage.
      </P>

      <H2>Changes</H2>
      <P>
        These terms may be updated from time to time; continued use after a change constitutes acceptance of
        the updated terms.
      </P>

      <H2>Termination</H2>
      <P>
        You may delete your account at any time from Settings, which immediately revokes connected platform
        access and removes your data as described in the <A href="/privacy">Privacy Policy</A>. We may suspend
        or terminate accounts that violate these terms.
      </P>

      <H2>Contact</H2>
      <P>
        <A href="mailto:dettinger.joel@gmail.com">dettinger.joel@gmail.com</A>
      </P>
    </>
  )
}
