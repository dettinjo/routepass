import type { Metadata } from 'next'
import { LegalTitle, H2, P, Ul, A } from '../legal-content'

export const metadata: Metadata = { title: 'Privacy Policy' }

export default function PrivacyPage() {
  return (
    <>
      <LegalTitle updated="2026-07-07">Privacy Policy</LegalTitle>

      <P>
        This policy describes what data RoutePass collects, why, and how it is protected. RoutePass syncs
        fitness activity data between platforms you connect (e.g. Strava, Komoot, Garmin, Intervals.icu) on
        your behalf. This instance is operated as a personal, non-commercial demo at routepass.online.
      </P>

      <H2>What we collect</H2>
      <Ul>
        <li><strong>Account data</strong> — email address and password (hashed with bcrypt), or your Google/GitHub account identifier if you sign in via OAuth.</li>
        <li><strong>Platform credentials</strong> — OAuth tokens (Strava, Google, GitHub) or encrypted credentials (Komoot, Garmin) for the services you choose to connect.</li>
        <li><strong>Activity data</strong> — GPX tracks and metadata (distance, elevation, sport type, name, timestamps) for activities that pass through a pipeline you configure.</li>
        <li><strong>Audit and usage data</strong> — a log of security-relevant actions on your account (connect/disconnect, export requests, deletion) and standard server request logs.</li>
      </Ul>

      <H2>How it&apos;s protected</H2>
      <Ul>
        <li>Komoot credentials and Strava/Google/GitHub tokens are encrypted at rest with AES-256 (Fernet); the encryption key never leaves the server environment.</li>
        <li>GPX downloads use short-lived presigned URLs rather than streaming raw data through shared infrastructure where object storage is enabled.</li>
        <li>All traffic to routepass.online is served over HTTPS (Let&apos;s Encrypt).</li>
      </Ul>

      <H2>Third-party services</H2>
      <P>
        Depending on which pipelines you configure, activity data is sent to the third-party platforms you
        explicitly connect (Strava, Komoot, Garmin Connect, Intervals.icu, Runalyze). Each of those services
        has its own privacy policy governing how it handles the data once received. RoutePass only sends data
        to a destination if you have created a pipeline routing activities there.
      </P>

      <H2>Data retention & deletion</H2>
      <P>
        You can export a complete copy of your data at any time (Settings → Export data), and delete your
        account and all associated data (activities, connections, GPX blobs) at any time. Deletion cascades
        immediately; a minimal audit trail (with the account reference removed) is retained for security and
        abuse-prevention purposes, consistent with GDPR Art. 17(3).
      </P>

      <H2>Your rights (GDPR)</H2>
      <P>
        If you are in the EU/EEA, you have the right to access, rectify, export, and erase your data, and to
        object to or restrict processing. The in-app export and account deletion tools cover most requests
        directly; for anything else, contact <A href="mailto:dettinger.joel@gmail.com">dettinger.joel@gmail.com</A>.
      </P>

      <H2>Self-hosting</H2>
      <P>
        RoutePass is MIT-licensed and self-hostable — if you would rather not use this shared instance, you
        can run your own copy with your own credentials and full control over your data. See the{' '}
        <A href="/docs/getting-started/self-hosting/">self-hosting guide</A>.
      </P>

      <H2>Contact</H2>
      <P>
        Questions about this policy or your data: <A href="mailto:dettinger.joel@gmail.com">dettinger.joel@gmail.com</A>.
      </P>
    </>
  )
}
