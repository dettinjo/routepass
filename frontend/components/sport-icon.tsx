import React from 'react'
import {
  IconBike,
  IconMountain,
  IconRoad,
  IconRun,
  IconTrekking,
  IconWalk,
  IconSwimming,
  IconSkiJumping,
  IconSnowflake,
  IconKayak,
  IconYoga,
  IconBarbell,
  IconMotorbike,
  IconGolf,
  IconBallTennis,
  IconSkateboard,
  IconWheelchair,
  IconSailboat,
  IconTreadmill,
  IconActivity,
  IconSnowboarding,
} from '@tabler/icons-react'

interface SportIconProps extends React.ComponentPropsWithoutRef<'svg'> {
  sportType: string
  size?: number | string
}

export function SportIcon({ sportType, size = 20, className, ...props }: SportIconProps) {
  const type = sportType.toLowerCase()

  // Grouped by logical categories
  if (type.includes('mtb') || type.includes('mountainbike') || type.includes('singletrack') || type.includes('downhill')) {
    return <IconMountain size={size} className={className} {...props} />
  }
  if (type.includes('e_') || type.includes('ebike') || type.includes('emountainbike')) {
    return <IconMotorbike size={size} className={className} {...props} />
  }
  if (type.includes('road') || type.includes('racebike') || type.includes('gravel')) {
    return <IconRoad size={size} className={className} {...props} />
  }
  if (type.includes('bike') || type.includes('bicycle') || type === 'ride' || type === 'virtualride') {
    return <IconBike size={size} className={className} {...props} />
  }
  if (type === 'trail_running' || type === 'trailrun' || type.includes('hike') || type.includes('hiking')) {
    return <IconTrekking size={size} className={className} {...props} />
  }
  if (type.includes('run') || type === 'jogging') {
    return <IconRun size={size} className={className} {...props} />
  }
  if (type.includes('walk')) {
    return <IconWalk size={size} className={className} {...props} />
  }
  if (type.includes('swim') || type === 'waterpolo') {
    return <IconSwimming size={size} className={className} {...props} />
  }
  if (type.includes('ski') || type.includes('snowshoe')) {
    return <IconSkiJumping size={size} className={className} {...props} />
  }
  if (type.includes('snowboard')) {
    return <IconSnowboarding size={size} className={className} {...props} />
  }
  if (type.includes('kayak') || type.includes('canoe') || type.includes('row')) {
    return <IconKayak size={size} className={className} {...props} />
  }
  if (type.includes('sail') || type.includes('surf') || type.includes('paddle')) {
    return <IconSailboat size={size} className={className} {...props} />
  }
  if (type.includes('yoga') || type.includes('pilates')) {
    return <IconYoga size={size} className={className} {...props} />
  }
  if (type.includes('weight') || type.includes('workout') || type.includes('crossfit') || type.includes('hiit')) {
    return <IconBarbell size={size} className={className} {...props} />
  }
  if (type.includes('golf')) {
    return <IconGolf size={size} className={className} {...props} />
  }
  if (type.includes('tennis') || type.includes('squash') || type.includes('racquet') || type.includes('pickleball')) {
    return <IconBallTennis size={size} className={className} {...props} />
  }
  if (type.includes('skate')) {
    return <IconSkateboard size={size} className={className} {...props} />
  }
  if (type.includes('wheelchair') || type.includes('handcycle')) {
    return <IconWheelchair size={size} className={className} {...props} />
  }
  if (type.includes('elliptical') || type.includes('stair') || type.includes('step')) {
    return <IconTreadmill size={size} className={className} {...props} />
  }
  if (type.includes('climb')) {
    return <IconMountain size={size} className={className} {...props} />
  }

  // Fallback
  return <IconActivity size={size} className={className} {...props} />
}
