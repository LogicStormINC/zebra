import { cn } from '@/lib/utils';

/**
 * Zebra 平台 Logo：条纹方块 + Z 字。
 * 纯 SVG，无外部资源依赖。
 */
export function ZebraLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox='0 0 32 32'
      fill='none'
      xmlns='http://www.w3.org/2000/svg'
      className={cn('text-primary', className)}
      aria-hidden='true'
    >
      <rect width='32' height='32' rx='7' className='fill-current opacity-10' />
      <path
        d='M9 8.5h14L12.5 23.5H23'
        stroke='currentColor'
        strokeWidth='3.2'
        strokeLinecap='round'
        strokeLinejoin='round'
      />
      <path d='M6 13.5h7' stroke='currentColor' strokeWidth='1.6' strokeLinecap='round' opacity='0.55' />
      <path d='M19 19h7' stroke='currentColor' strokeWidth='1.6' strokeLinecap='round' opacity='0.55' />
    </svg>
  );
}
