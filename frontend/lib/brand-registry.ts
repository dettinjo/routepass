export type PlatformKey =
  | 'strava'
  | 'komoot'
  | 'garmin'
  | 'polar'
  | 'wahoo'
  | 'intervals_icu'
  | 'runalyze'
  | 'trainingpeaks'
  | 'webhook'
  | 'suunto'
  | 'local'

export interface BrandConfig {
  id: string
  name: string
  url?: string
  colors: {
    primary: string
  }
  assets: {
    regular: string
    white: string
    black: string
  }
}

export const ROUTEPASS_BRAND: BrandConfig = {
  id: 'routepass',
  name: 'RoutePass',
  url: 'https://routepass.com',
  colors: {
    primary: '#3ECFAF', // Mint green
  },
  assets: {
    regular: '/icons/Regular/routepass_icon.svg',
    white: '/icons/White/routepass_icon_mono_white.svg',
    black: '/icons/Black/routepass_icon_mono_black.svg',
  },
}

export const PLATFORM_BRANDS: Record<PlatformKey, BrandConfig> = {
  strava: {
    id: 'strava',
    name: 'Strava',
    url: 'https://www.strava.com',
    colors: { primary: '#FC4C02' },
    assets: {
      regular: '/icons/Regular/strava_icon.svg',
      white: '/icons/White/strava_icon_mono_white.svg',
      black: '/icons/Black/strava_icon_mono_black.svg',
    },
  },
  komoot: {
    id: 'komoot',
    name: 'Komoot',
    url: 'https://www.komoot.com',
    colors: { primary: '#6AA127' },
    assets: {
      regular: '/icons/Regular/komoot_icon.svg',
      white: '/icons/White/komoot_icon_mono_white.svg',
      black: '/icons/Black/komoot_icon_mono_black.svg',
    },
  },
  garmin: {
    id: 'garmin',
    name: 'Garmin Connect',
    url: 'https://connect.garmin.com',
    colors: { primary: '#2eace2' },
    assets: {
      regular: '/icons/Regular/garmin_icon.svg',
      white: '/icons/White/garmin_icon_mono_white.svg',
      black: '/icons/Black/garmin_icon_mono_black.svg',
    },
  },
  polar: {
    id: 'polar',
    name: 'Polar Flow',
    url: 'https://flow.polar.com',
    colors: { primary: '#C8173D' },
    assets: {
      regular: '/icons/Regular/polar_icon.svg',
      white: '/icons/White/polar_icon_mono_white.svg',
      black: '/icons/Black/polar_icon_mono_black.svg',
    },
  },
  wahoo: {
    id: 'wahoo',
    name: 'Wahoo',
    url: 'https://systm.wahoofitness.com',
    colors: { primary: '#A3A3A3' },
    assets: {
      regular: '/icons/Regular/wahoo_icon.svg',
      white: '/icons/White/wahoo_icon_mono_white.svg',
      black: '/icons/Black/wahoo_icon_mono_black.svg',
    },
  },
  suunto: {
    id: 'suunto',
    name: 'Suunto',
    url: 'https://www.suunto.com',
    colors: { primary: '#e1001a' },
    assets: {
      regular: '/icons/Regular/suunto_icon.svg',
      white: '/icons/White/suunto_icon_mono_white.svg',
      black: '/icons/Black/suunto_icon_mono_black.svg',
    },
  },
  intervals_icu: {
    id: 'intervals_icu',
    name: 'Intervals.icu',
    url: 'https://intervals.icu',
    colors: { primary: '#dd0447' },
    assets: {
      regular: '/icons/Regular/intervals_logo.svg',
      white: '/icons/White/intervals_logo_mono_white.svg',
      black: '/icons/Black/intervals_logo_mono_black.svg',
    },
  },
  runalyze: {
    id: 'runalyze',
    name: 'Runalyze',
    url: 'https://runalyze.com',
    colors: { primary: '#7dbe63' },
    assets: {
      regular: '/icons/Regular/runalyze_icon.svg',
      white: '/icons/White/runalyze_icon_mono_white.svg',
      black: '/icons/Black/runalyze_icon_mono_black.svg',
    },
  },
  trainingpeaks: {
    id: 'trainingpeaks',
    name: 'TrainingPeaks',
    url: 'https://www.trainingpeaks.com',
    colors: { primary: '#3074f8' },
    assets: {
      regular: '/icons/Regular/trainingpeaks_icon.svg',
      white: '/icons/White/trainingpeaks_icon_mono_white.svg',
      black: '/icons/Black/trainingpeaks_icon_mono_black.svg',
    },
  },
  webhook: {
    id: 'webhook',
    name: 'Webhook',
    url: '#',
    colors: { primary: '#c93762' },
    assets: {
      regular: '/icons/Regular/webhook_icon.svg',
      white: '/icons/White/webhook_icon_mono_white.svg',
      black: '/icons/Black/webhook_icon_mono_black.svg',
    },
  },
  local: {
    id: 'local',
    name: 'Local',
    url: '#',
    colors: { primary: '#4F46E5' },
    assets: {
      regular: '/icons/Regular/local_icon.svg',
      white: '/icons/White/local_icon_mono_white.svg',
      black: '/icons/Black/local_icon_mono_black.svg',
    },
  },
}

// Helper function to get brand configuration safely
export function getBrand(key: PlatformKey | 'routepass'): BrandConfig {
  if (key === 'routepass') return ROUTEPASS_BRAND
  return PLATFORM_BRANDS[key]
}
