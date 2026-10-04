"""Constructed calibration prose, not independent natural contest tasks."""
from fsm_contract import INTRO

def full(n=6, names=('sense','phase','future','lit','ready'), label='Q'):
    signal,state,next_name,*moore=names
    lines=[INTRO,'',f'- input {signal}',f'- input {state} ({n} bits)',f'- output {next_name} ({n} bits)']+[f'- output {name}' for name in moore]
    lines+=['',f'Given the follow state machine with 1 input and {len(moore)} outputs (the outputs are given as "({", ".join(moore)})"):', '']
    truth=[]
    for i in range(n):
        outs=[int(i==n-1),int(i in [n-2,n-1])]
        for v in [0,1]:
            target=i if v==0 else (i+1)%n
            lines.append(f'{label}{i} ({", ".join(str(b) for b in outs)}) --{v}--> {label}{target}')
            truth.append((i,v,target,outs))
    lines+=['',f'Suppose this state machine uses one-hot encoding, where {state}[0] through {state}[{n-1}] correspond to the states {label}0 though {label}{n-1}, respectively.',
      f'The outputs are zero unless otherwise specified. The {next_name}[0] through {next_name}[{n-1}] correspond to the transition to next states {label}0 though {label}{n-1}.',
      f'For example, The {next_name}[1] is set to 1 when the next state is {label}1 , otherwise, it is set to 0.',
      f'Here, the input {state}[{n-1}:0] can be a combinational of multiple states, and the TopModule is expected to response.', 'For example:',
      f'When the {state}[{n-1}:0] = {n}\'b{format(20,f"0{n}b")}, {state}[4] == 1, and {state}[2] == 1, the states includes {label}4, and {label}2 states.',
      'The module should implement the state transition logic and output logic portions of the state machine (but not the state flip-flops).',
      f'You are given the current state in {state}[{n-1}:0] and must implement {next_name}[{n-1}:0] and the two outputs.','']
    return '\n'.join(lines),truth

def partial(n=5, names=('trigger','finish','accept','active','first_next','last_next','busy','done'), explicit=False):
    a,b,d,state,first,last,busy,done=names;labels=[f'Node{i}' for i in range(n)]
    lines=[INTRO,'']+[f'- input {x}' for x in [a,b,d]]+[f'- input {state} ({n} bits)']+[f'- output {x}' for x in [first,last,busy,done]]
    lines+=['',f'The module should implement the following Moore state machine with 3 input ({a}, {b}, {d}) and 2 outputs ({busy}, {done}).',
       "Unless otherwise stated in the diagram below, assume outputs are 0 and inputs are don't cares.",
       'state (output) --input--> next state','-------------------------------------------']
    truth=[]
    for i in range(n):
        outs=[]
        if i==n-2:outs=[busy+'=1']
        if i==n-1:outs=[done+'=1']
        cond_name=[a,b,d][i%3]
        for v in [0,1]:
            target=i if v==0 else (i+1)%n
            lines.append(f'{labels[i]} ({", ".join(outs)}) --{cond_name}={v}--> {labels[target]}')
            truth.append((i,cond_name,v,target,[int(i==n-2),int(i==n-1)]))
    codes=[f"{n}'b{format(1<<i,f'0{n}b')}" for i in range(n)]
    encoding=', '.join(codes if explicit else codes[:3]+['...']+codes[-1:])
    lines+=['',f'At reset, the state machine starts in state "{labels[0]}". Derive next-state logic equations and output logic equations by inspection assuming the following one-hot encoding is used: ({", ".join(labels)}) = ({encoding})',
      'Derive state transition and output logic equations by inspection assuming a one-hot encoding.',
      'Implement only the state transition logic and output logic (the combinational logic portion) for this state machine.',
      'Write code that generates the following signals:',
      f'- {first} -- Assert when next-state is {labels[0]} state',f'- {last} -- Assert when next-state is {labels[-1]} state',
      f'- {busy} -- output logic',f'- {done} -- output logic','']
    return '\n'.join(lines),truth
