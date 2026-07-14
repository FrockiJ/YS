def make_citation(filename: str, page: int | None, chunk_idx: int | None):
    cite={'source':filename}; 
    if page is not None: cite['page']=page
    if chunk_idx is not None: cite['frag']=chunk_idx
    return cite
