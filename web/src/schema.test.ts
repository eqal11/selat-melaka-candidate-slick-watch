import {describe,expect,it} from 'vitest';
import {ScoreSchema} from './score-schema';
import {ResultSchema,ValidationCasesSchema} from './schema';
describe('real-result validation',()=>{
 it('rejects responses without a traceable real scene',()=>{expect(ResultSchema.safeParse({data_label:'UNLABELLED'}).success).toBe(false)});
 it('requires a source-linked validation register with at least eight cases',()=>{expect(ValidationCasesSchema.safeParse({data_label:'REAL',scene_search_note:'unsearched',cases:[]}).success).toBe(false)});
 it('rejects heuristic scores outside 0–100',()=>{expect(ScoreSchema.safeParse(101).success).toBe(false);expect(ScoreSchema.safeParse(65).success).toBe(true)});
});
