import { z } from 'zod';
export const ScoreSchema = z.number().min(0).max(100);
