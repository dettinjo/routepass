import type { ComponentType, CSSProperties } from "react";
import {
  IconActivity,
  IconAlertTriangle,
  IconApi as TApi,
  IconArrowDown as TArrowDown,
  IconArrowRight as TArrowRight,
  IconArrowUp as TArrowUp,
  IconArrowsExchange,
  IconBallFootball,
  IconBallTennis,
  IconBarbell,
  IconBike,
  IconBolt,
  IconCalendar as TCalendar,
  IconChartBar,
  IconCheck as TCheck,
  IconChevronLeft,
  IconChevronRight,
  IconCircleCheck,
  IconCircleDashed,
  IconClock,
  IconCloudDownload,
  IconDownload as TDownload,
  IconExternalLink,
  IconFilter as TFilter,
  IconFlame,
  IconGauge,
  IconGolf,
  IconHeart,
  IconHistory as THistory,
  IconHome as THome,
  IconInfoCircle,
  IconKayak,
  IconKey as TKey,
  IconListDetails,
  IconLock as TLock,
  IconLockOpen,
  IconMap as TMap,
  IconMountain,
  IconPlayerPlay,
  IconPlugConnected,
  IconPlus as TPlus,
  IconRefresh as TRefresh,
  IconRipple,
  IconRoad,
  IconRoute,
  IconRuler,
  IconRun,
  IconSailboat,
  IconScooterElectric,
  IconSearch as TSearch,
  IconSelectAll,
  IconSettings as TSettings,
  IconSkateboard,
  IconSkiJumping,
  IconSnowboarding,
  IconSnowflake,
  IconSparkles as TSparkles,
  IconStairsUp,
  IconStopwatch,
  IconSwimming,
  IconTarget as TTarget,
  IconTemperature,
  IconTimeline as TTimeline,
  IconTrash as TTrash,
  IconTrekking,
  IconTrendingUp,
  IconTrophy as TTrophy,
  IconUser as TUser,
  IconWalk,
  IconWheelchair,
  IconX as TX,
  IconYoga,
} from "@tabler/icons-react";

type P = { width?: number; height?: number; size?: number; className?: string; style?: CSSProperties };
const wrap = (I: ComponentType<any>) =>
  function Icon({ width, height, size, ...p }: P) {
    return <I size={size ?? width ?? height ?? 18} stroke={1.8} {...p} />;
  };

export const IconHome = wrap(THome);
export const IconList = wrap(IconListDetails);
export const IconChart = wrap(IconChartBar);
export const IconSync = wrap(IconArrowsExchange);
export const IconSettings = wrap(TSettings);
export const IconRefresh = wrap(TRefresh);
export const IconArrowUp = wrap(TArrowUp);
export const IconArrowDown = wrap(TArrowDown);
export const IconLeft = wrap(IconChevronLeft);
export const IconRight = wrap(IconChevronRight);
export const IconPlus = wrap(TPlus);
export const IconTrash = wrap(TTrash);
export const IconLock = wrap(TLock);
export const IconUnlock = wrap(IconLockOpen);
export const IconExternal = wrap(IconExternalLink);
export const IconDownload = wrap(TDownload);
export const IconX = wrap(TX);
export const IconCheck = wrap(TCheck);
export const IconFilter = wrap(TFilter);
export const IconSearch = wrap(TSearch);
export const IconWarn = wrap(IconAlertTriangle);
export const IconInfo = wrap(IconInfoCircle);
export const IconDone = wrap(IconCircleCheck);
export const IconPending = wrap(IconCircleDashed);
export const IconHistory = wrap(THistory);
export const IconImport = wrap(IconCloudDownload);
export const IconPlay = wrap(IconPlayerPlay);
export const IconArrowRight = wrap(TArrowRight);
export const IconMap = wrap(TMap);
export const IconTrophy = wrap(TTrophy);
export const IconCalendar = wrap(TCalendar);
export const IconSparkles = wrap(TSparkles);
export const IconTimeline = wrap(TTimeline);
export const IconTarget = wrap(TTarget);
export const IconApi = wrap(TApi);
export const IconKey = wrap(TKey);
export const IconUser = wrap(TUser);
export const IconSelect = wrap(IconSelectAll);
export const IconPlug = wrap(IconPlugConnected);

/** Metric icons used next to numbers. */
export const MetricIcon = {
  distance: wrap(IconRoute),
  time: wrap(IconClock),
  elapsed: wrap(IconStopwatch),
  elevation: wrap(IconTrendingUp),
  climb: wrap(IconStairsUp),
  speed: wrap(IconGauge),
  hr: wrap(IconHeart),
  power: wrap(IconBolt),
  load: wrap(IconFlame),
  temp: wrap(IconTemperature),
  count: wrap(IconActivity),
  days: wrap(TCalendar),
  length: wrap(IconRuler),
};
export type MetricKey = keyof typeof MetricIcon;

const SPORT_ICONS: [RegExp, ComponentType<any>][] = [
  [/^E(Bike|MountainBike)Ride$/, IconScooterElectric],
  [/MountainBike|Downhill/i, IconMountain],
  [/Gravel|VirtualRide|Velomobile|Handcycle/i, IconRoad],
  [/Ride$/, IconBike],
  [/TrailRun|Hike/, IconTrekking],
  [/Run$/, IconRun],
  [/Wheelchair/, IconWheelchair],
  [/Walk/, IconWalk],
  [/Snowboard/, IconSnowboarding],
  [/Ski|Snowshoe/, IconSkiJumping],
  [/IceSkate/, IconSnowflake],
  [/Swim/, IconSwimming],
  [/Kayak|Canoe|Row|Paddl/, IconKayak],
  [/Surf|Kite|Wind/, IconRipple],
  [/Sail/, IconSailboat],
  [/Climb/, IconMountain],
  [/Skate|RollerSki/, IconSkateboard],
  [/Yoga|Pilates/, IconYoga],
  [/Weight|Crossfit|HighIntensity|Elliptical|StairStepper|Workout/, IconBarbell],
  [/Golf/, IconGolf],
  [/Soccer/, IconBallFootball],
  [/Tennis|Badminton|Squash|Racquet|Pickle/, IconBallTennis],
];

const FAMILY_ICONS: Record<string, ComponentType<any>> = {
  ride: IconBike,
  run: IconRun,
  walk: IconTrekking,
  winter: IconSkiJumping,
  water: IconSwimming,
  other: IconActivity,
};

export function SportIcon({ sport, family, size = 18, className, style }: {
  sport?: string; family?: string; size?: number; className?: string; style?: CSSProperties;
}) {
  const I = (sport && SPORT_ICONS.find(([re]) => re.test(sport))?.[1]) || (family && FAMILY_ICONS[family]) || IconActivity;
  return <I size={size} stroke={1.8} className={className} style={style} />;
}

const STRAVA_PATH = "M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066m-7.008-5.599l2.836 5.598h4.172L10.463 0l-7 13.828h4.169";
const KOMOOT_PATH = "M9.8 14.829l2.2-3.43 2.2 3.43 5.962 5.962A11.946 11.946 0 0 1 12 24c-3.043 0-5.935-1.14-8.162-3.209zM0 12C0 5.385 5.385 0 12 0c6.62 0 12 5.385 12 12 0 2.663-.855 5.175-2.469 7.284l-6.018-6.018c.15-.412.226-.839.226-1.27A3.743 3.743 0 0 0 12 8.257a3.743 3.743 0 0 0-3.739 3.739c0 .431.075.858.226 1.27l-6.018 6.018A11.865 11.865 0 0 1 0 12Z";

/** Official Strava / Komoot marks (the same SVGs as RoutePass v1). mono = current text colour. */
export function BrandIcon({ provider, size = 18, mono = false, title }: { provider: string; size?: number; mono?: boolean; title?: string }) {
  const strava = provider === "strava";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={title ?? providerName(provider)} style={{ flex: "none" }}>
      {title && <title>{title}</title>}
      <path fill={mono ? "currentColor" : strava ? "#FC4C02" : "#6AA127"} d={strava ? STRAVA_PATH : KOMOOT_PATH} />
    </svg>
  );
}

export const providerName = (p: string) => (p === "strava" ? "Strava" : "Komoot");
