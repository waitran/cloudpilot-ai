import { useQuery } from '@tanstack/react-query';
import { getSystemInfo } from './api';

export function useSystemInfo() {
  return useQuery({
    queryKey: ['system-info'],
    queryFn: ({ signal }) => getSystemInfo(signal),
    staleTime: 5000,
    refetchInterval: 15000,
    retry: 1,
  });
}
