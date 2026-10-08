"""Exact synthetic fixture definition reused from original99 controls."""
def fixture(n=5, k=2, module="GraphUnit", pin="sample", state="active",
            nxt="future", prefix="Node", edges=None, masks=None):
    edges = edges if edges is not None else {(i,v):(i*3+v+1)%n for i in range(n) for v in (0,1)}
    masks = masks if masks is not None else [[int((i+j)%3 == 0) for j in range(k)] for i in range(n)]
    outputs = ["flag"+str(i) for i in range(k)]
    ports = [("input",pin,1),("input",state,n),("output",nxt,n)] + [("output",o,1) for o in outputs]
    listing = "\n".join(" - "+d+" "+name+((" ("+str(w)+" bits)") if w>1 else "") for d,name,w in ports)
    graph = "\n".join(prefix+str(i)+" ("+", ".join(map(str,masks[i]))+") --"+str(v)+"--> "+prefix+str(edges[i,v]) for i in range(n) for v in (0,1))
    example = format((1<<(n-1))|1,"0"+str(n)+"b")
    prompt = ("I would like you to implement a module named "+module+" with the following\n"
        "interface. All input and output ports are one bit unless otherwise\nspecified.\n\n"+listing+
        '\n\nGiven the following state machine with 1 input and '+str(k)+' outputs (the outputs\nare given as "('+
        ", ".join(outputs)+')"):\n\n'+graph+"\n\n"
        "Suppose this state machine uses one-hot encoding, where "+state+"[0] through\n"+state+"["+str(n-1)+
        "] correspond to the states "+prefix+"0 through "+prefix+str(n-1)+", respectively. The outputs\n"
        "are zero unless otherwise specified. The "+nxt+"[0] through "+nxt+"["+str(n-1)+"]\n"
        "correspond to the transition to next states "+prefix+"0 through "+prefix+str(n-1)+". For example, The\n"+
        nxt+"[1] is set to 1 when the next state is "+prefix+"1 , otherwise, it is set to 0.\n\n"
        "Here, the input "+state+"["+str(n-1)+":0] can be a combination of multiple states, and\nthe "+module+
        " is expected to response.\nFor example:\nWhen the "+state+"["+str(n-1)+":0] = "+str(n)+"'b"+example+", "+
        state+"["+str(n-1)+"] == 1, and "+state+"[0] == 1, the\nstates includes "+prefix+str(n-1)+", and "+prefix+"0 states.\n\n"
        "The module should implement the state transition logic and output logic\nportions of the state machine (but not the state flip-flops). You are\n"
        "given the current state in "+state+"["+str(n-1)+":0] and must implement "+nxt+"["+str(n-1)+":0]\nand the "+
        {1:"one",2:"two",3:"three",4:"four"}[k]+" outputs.\n")
    interface = "module "+module+" ("+", ".join(d+" wire "+("["+str(w-1)+":0] " if w>1 else "")+name for d,name,w in ports)+");\nendmodule\n"
    return prompt, interface, dict(n=n,k=k,edges=edges,masks=masks,pin=pin,state=state,nxt=nxt,outputs=outputs)
