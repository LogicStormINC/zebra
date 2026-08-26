'use client';

import { useState, type ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Icons } from '@/components/icons';

/** 向导表单行：label + 控件 + 说明。 */
export function FormRow({
  label,
  required,
  hint,
  children
}: {
  label: string;
  required?: boolean;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className='flex flex-col gap-1.5'>
      <Label>
        {label}
        {required && <span className='text-destructive'>*</span>}
      </Label>
      {children}
      {hint && <p className='text-muted-foreground text-xs'>{hint}</p>}
    </div>
  );
}

/** 多值输入（Allowed Origins / Tags / Algorithms 等）：徽标 + 追加输入。 */
export function MultiValueInput({
  values,
  onChange,
  placeholder = '输入后回车或点击添加',
  emptyText = '暂未配置'
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  emptyText?: string;
}) {
  const [pending, setPending] = useState('');

  const add = () => {
    const value = pending.trim();
    if (value.length === 0 || values.includes(value)) {
      setPending('');
      return;
    }
    onChange([...values, value]);
    setPending('');
  };

  return (
    <div className='flex flex-col gap-2'>
      <div className='flex gap-2'>
        <Input
          value={pending}
          placeholder={placeholder}
          onChange={(event) => setPending(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
        />
        <Button type='button' variant='outline' size='icon' aria-label='添加' onClick={add}>
          <Icons.add className='size-4' />
        </Button>
      </div>
      {values.length === 0 ? (
        <p className='text-muted-foreground text-xs'>{emptyText}</p>
      ) : (
        <div className='flex flex-wrap gap-1.5'>
          {values.map((value) => (
            <Badge key={value} variant='secondary' className='gap-1 font-mono'>
              {value}
              <button
                type='button'
                aria-label={`移除 ${value}`}
                className='hover:bg-muted rounded p-0.5'
                onClick={() => onChange(values.filter((item) => item !== value))}
              >
                <Icons.close className='size-3' />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
