from fastapi import APIRouter
router = APIRouter()
@router.get('/debug/health')
def health(): return {'ok': True}
