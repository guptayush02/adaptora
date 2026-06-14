#!/usr/bin/env python3
"""
Example usage of the LLM Token Optimizer Middleware

This script demonstrates how to use the middleware for:
1. Processing simple queries (handled by Ollama)
2. Processing complex queries (routed to advanced models)
3. Using bypass keywords
4. Checking cache hits
5. Getting user statistics
"""

import requests
import json
from typing import Dict, Any

# Middleware API URL
API_URL = "http://localhost:8000"


def print_response(response_data: Dict[str, Any]) -> None:
    """Pretty print API response"""
    print("\n" + "=" * 60)
    print(f"Response: {response_data['response'][:200]}..." if len(response_data.get('response', '')) > 200 else response_data['response'])
    print(f"Model Used: {response_data['model_used']}")
    print(f"Cache Hit: {response_data['cache_hit']}")
    print(f"Complexity Level: {response_data['complexity_level']}")
    print(f"Tokens Used: {response_data['tokens_used']}")
    print(f"Processing Time: {response_data['processing_time_ms']:.2f}ms")
    if response_data.get('prompt_optimization'):
        print(f"Optimization: {response_data['prompt_optimization']}")
    print("=" * 60)


def test_health_check() -> bool:
    """Test if middleware is running"""
    print("\n📋 Testing Health Check...")
    try:
        response = requests.get(f"{API_URL}/api/health", timeout=5)
        if response.status_code == 200:
            print("✅ Middleware is healthy!")
            return True
        print("❌ Middleware returned error")
        return False
    except Exception as e:
        print(f"❌ Could not connect to middleware: {e}")
        return False


def test_simple_query():
    """Test a simple query (should use Ollama)"""
    print("\n🟢 Testing Simple Query (Should use Ollama)...")
    
    payload = {
        "prompt": "What is the capital of France?",
        "model": "ollama",
        "temperature": 0.7,
        "user_id": "demo_user"
    }
    
    try:
        response = requests.post(f"{API_URL}/api/process", json=payload, timeout=30)
        if response.status_code == 200:
            print_response(response.json())
            print("✅ Simple query processed successfully!")
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_medium_query():
    """Test a medium complexity query"""
    print("\n🟡 Testing Medium Complexity Query...")
    
    payload = {
        "prompt": "Explain how machine learning algorithms work with examples",
        "model": "ollama",
        "temperature": 0.7,
        "user_id": "demo_user"
    }
    
    try:
        response = requests.post(f"{API_URL}/api/process", json=payload, timeout=30)
        if response.status_code == 200:
            print_response(response.json())
            print("✅ Medium query processed successfully!")
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_cache_hit():
    """Test cache hit by sending same query twice"""
    print("\n💾 Testing Cache Mechanism...")
    
    payload = {
        "prompt": "What is Python?",
        "model": "ollama",
        "temperature": 0.7,
        "user_id": "demo_user"
    }
    
    print("  First request (should miss cache)...")
    try:
        response1 = requests.post(f"{API_URL}/api/process", json=payload, timeout=30)
        if response1.status_code == 200:
            data1 = response1.json()
            print(f"  Cache Hit: {data1['cache_hit']}")
            print(f"  Processing Time: {data1['processing_time_ms']:.2f}ms")
            
            print("  Second request (should hit cache)...")
            response2 = requests.post(f"{API_URL}/api/process", json=payload, timeout=30)
            if response2.status_code == 200:
                data2 = response2.json()
                print(f"  Cache Hit: {data2['cache_hit']}")
                print(f"  Processing Time: {data2['processing_time_ms']:.2f}ms")
                
                if data2['cache_hit']:
                    print("✅ Cache working! Second request was much faster")
                else:
                    print("⚠️  Cache hit not detected (Redis might not be running)")
            else:
                print(f"❌ Error on second request: {response2.status_code}")
        else:
            print(f"❌ Error on first request: {response1.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_bypass_keywords():
    """Test bypass keywords to force advanced model"""
    print("\n⚡ Testing Bypass Keywords (Forces Advanced Model)...")
    
    payload = {
        "prompt": "URGENT: Solve this complex algorithm problem: ...",
        "model": "gpt-4",  # Will use this if OpenAI key is configured
        "temperature": 0.7,
        "user_id": "demo_user"
    }
    
    print("  Query contains 'URGENT' keyword")
    print("  This should bypass Ollama and route to advanced model")
    
    try:
        response = requests.post(f"{API_URL}/api/process", json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            print(f"  Model Used: {data['model_used']}")
            if data['model_used'] != 'ollama':
                print("✅ Bypass keyword worked! Routed to advanced model")
            else:
                print("ℹ️  Routed to Ollama (OpenAI key may not be configured)")
        else:
            print(f"❌ Error: {response.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_user_statistics():
    """Get user statistics"""
    print("\n📊 Testing User Statistics...")
    
    try:
        response = requests.get(f"{API_URL}/api/stats/demo_user", timeout=5)
        if response.status_code == 200:
            stats = response.json()
            print(f"  User ID: {stats['user_id']}")
            print(f"  Total Queries: {stats['total_queries']}")
            print(f"  Total Tokens: {stats['total_tokens']}")
            print(f"  Average Tokens per Query: {stats['average_tokens_per_query']:.2f}")
            print(f"  Models Used: {stats['models_used']}")
            print("✅ Statistics retrieved successfully!")
        else:
            print(f"❌ Error: {response.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🚀 LLM Token Optimizer Middleware - Example Usage")
    print("=" * 60)
    
    # Check if middleware is running
    if not test_health_check():
        print("\n⚠️  Please ensure the middleware is running:")
        print("   python main.py")
        return
    
    # Also ensure Ollama is running
    print("\n⚠️  Make sure Ollama is running:")
    print("   ollama serve")
    print("   ollama pull mistral")
    
    # Run tests
    test_simple_query()
    test_medium_query()
    test_cache_hit()
    test_bypass_keywords()
    test_user_statistics()
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)
    print("\n📚 API Documentation available at:")
    print("   http://localhost:8000/docs")
    print("\n📖 README: See README.md for detailed documentation")


if __name__ == "__main__":
    main()
