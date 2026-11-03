import os
import sys
import time
from db_manager import get_stats, get_unfilled_records

def show_status():
    stats = get_stats()
    unfilled = get_unfilled_records()

    print("\n" + "=" * 55)
    print(f"{'ZEN DATA PROTSK - LIVE AUTOMATION STATUS':^55}")
    print("=" * 55)
    print(f" Total Completed in Database:   {stats['total_completed']}")
    print(f" Total Unfilled / Pending:      {stats['total_unfilled']}")
    print(f" Total Resolved Unfilled:       {stats['total_resolved']}")
    print(f" Last Completed QR:             QRCode - {stats['last_completed_qr']}")
    print(f" Next QR in Queue:              QRCode - {stats['next_qr']}")
    
    # Brain Model Info
    try:
        from brain_engine import get_brain_engine
        brain = get_brain_engine()
        meta = brain.metadata
        print("-" * 55)
        print(f" Adaptive Brain Model:          v{meta.get('version', '2.0')}")
        print(f" Cards Learned in Memory:       {meta.get('total_cards_trained', 0)}")
        print(f" Domain Knowledge Graph:        {meta.get('unique_domains', 0)} companies mapped")
        print(f" Dynamic Exemplar Memory:       {meta.get('exemplar_count', 0)} cards indexed")
    except Exception:
        pass
    print("-" * 55)
    
    pending = [r for r in unfilled if r.get('status') != 'resolved']
    if not pending:
        print(" [OK] All recent forms resolved! Zero pending failures.")
    else:
        print(f" [!] Pending Unfilled / Failed ({len(pending)} forms):")
        for r in pending[:5]:
            print(f"     - {r['qr_label']}: {r.get('reason', '')[:35]}")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    show_status()
